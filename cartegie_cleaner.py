import csv, re, sys, os, threading, queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

EXPECTED = ['IdBase','IdUser','Adresse EMail','email sha 256','Date dernière inscription','Dernière provenance','Civilité','Nom','Prénom','Adresse','Ville','CP','Pays','Date de naissance','Tel Fixe','Tel Mobile','tel_verif','Dernière ouverture (MARKETING)','Date Dernier Clic','statut_immo','CSP','RGPD Consentement ouverture','alcool','animaux','association','assurance','auto','banque','beauté','bonreduc','crédit/rac','defiscalisation/finance','eshopping','formation','hightech','Immobilier','isolation','jardin','jeuxconcours','loisirs','maman','minceur','mutuelle','newsletter','panel','sante/beauté','santé/bien-être','senior','travaux','Voyages']
NEWCOL='DATE_CONSENTEMENT_TELEMARKETING'
EMAIL_RE=re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

def detect_encoding(path):
    raw=Path(path).read_bytes()[:100000]
    if raw.startswith(b'\xef\xbb\xbf'): return 'utf-8-sig'
    try: raw.decode('utf-8'); return 'utf-8'
    except UnicodeDecodeError: return 'latin1'

def norm_header(v):
    # Compare le DE sans tenir compte de la casse ni des espaces parasites.
    return ' '.join((v or '').strip().casefold().split())

def norm_phone(v): return re.sub(r'[^0-9+]','',v or '')
def valid_phone(v):
    if not v.strip(): return True
    x=norm_phone(v).replace('+33','0',1) if norm_phone(v).startswith('+33') else norm_phone(v)
    return bool(re.fullmatch(r'0[1-9]\d{8}',x))
def valid_cp(v):
    if not v.strip(): return True
    x=v.strip()
    return bool(re.fullmatch(r'(?:0[1-9]|[1-8]\d|9[0-5]|2[ABab])\d{3}',x))
def valid_date(v):
    if not v.strip(): return True
    s=v.strip()
    for fmt in ('%Y-%m-%d %H:%M:%S','%Y-%m-%d','%d/%m/%Y %H:%M:%S','%d/%m/%Y'):
        try: datetime.strptime(s,fmt); return True
        except ValueError: pass
    return False

def process(src, out, logq):
    enc=detect_encoding(src)
    counts={'lignes':0,'emails_invalides':0,'cp_invalides':0,'tel_fixe_invalides':0,'tel_mobile_invalides':0,'dates_inscription_invalides':0,'dates_consentement_renseignees':0,'lignes_structure_invalides':0}
    anomalies=[]
    with open(src,'r',encoding=enc,newline='') as fi:
        r=csv.reader(fi)
        try: header=next(r)
        except StopIteration: raise ValueError('Le fichier est vide.')
        expected_norm=[norm_header(x) for x in EXPECTED]
        header_norm=[norm_header(x) for x in header]
        if header_norm != expected_norm:
            missing=[EXPECTED[i] for i,x in enumerate(expected_norm) if x not in header_norm]
            extra=[header[i] for i,x in enumerate(header_norm) if x not in expected_norm]
            raise ValueError(f'DE non conforme. Colonnes lues: {len(header)} au lieu de 50. Manquantes: {missing or "aucune"}. Supplémentaires: {extra or "aucune"}.')
        with open(out,'w',encoding=enc,newline='') as fo:
            w=csv.writer(fo, quoting=csv.QUOTE_MINIMAL)
            w.writerow(header+[NEWCOL])
            for row in r:
                counts['lignes']+=1; n=counts['lignes']
                if len(row)!=50:
                    counts['lignes_structure_invalides']+=1
                    anomalies.append((n+1,'STRUCTURE',f'{len(row)} champs au lieu de 50'))
                    continue
                email=row[2].strip(); cp=row[11].strip(); fixe=row[14].strip(); mob=row[15].strip(); dt=row[4].strip()
                if email and not EMAIL_RE.match(email): counts['emails_invalides']+=1; anomalies.append((n+1,'EMAIL',email))
                if not valid_cp(cp): counts['cp_invalides']+=1; anomalies.append((n+1,'CP',cp))
                if not valid_phone(fixe): counts['tel_fixe_invalides']+=1; anomalies.append((n+1,'TEL_FIXE',fixe))
                if not valid_phone(mob): counts['tel_mobile_invalides']+=1; anomalies.append((n+1,'TEL_MOBILE',mob))
                if not valid_date(dt): counts['dates_inscription_invalides']+=1; anomalies.append((n+1,'DATE_INSCRIPTION',dt))
                if dt: counts['dates_consentement_renseignees']+=1
                w.writerow(row+[dt])
                if n%50000==0: logq.put(('progress',n))
    report=Path(out).with_name(Path(out).stem+'_RAPPORT.txt')
    anomaly_file=Path(out).with_name(Path(out).stem+'_ANOMALIES.csv')
    with open(report,'w',encoding='utf-8') as f:
        f.write('CARTEGIE CLEANER - RAPPORT DE CONTROLE\n')
        f.write('='*42+'\n')
        f.write(f'Fichier source : {src}\nFichier produit : {out}\nEncodage : {enc}\n\n')
        f.write('DE : 50 colonnes source conformes + DATE_CONSENTEMENT_TELEMARKETING en dernière colonne.\n')
        f.write('Règle : DATE_CONSENTEMENT_TELEMARKETING = Date dernière inscription. Aucun filtre d’ancienneté téléphone.\n\n')
        for k,v in counts.items(): f.write(f'{k.replace("_"," ").capitalize()} : {v:,}\n'.replace(',',' '))
        f.write(f'Anomalies détaillées : {len(anomalies):,}\n'.replace(',',' '))
    with open(anomaly_file,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter=';'); w.writerow(['LIGNE_SOURCE','TYPE','VALEUR']); w.writerows(anomalies)
    return counts, str(report), str(anomaly_file)

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('Cartegie Cleaner v1.0.1'); self.geometry('760x520'); self.minsize(700,480)
        self.q=queue.Queue(); self.src=tk.StringVar(); self.status=tk.StringVar(value='Sélectionne un export Mindbaz Cartegie.')
        ttk.Label(self,text='Cartegie Cleaner',font=('Segoe UI',20,'bold')).pack(pady=(20,4))
        ttk.Label(self,text='DE Cartegie figé • contrôles classiques • gros fichiers en streaming').pack()
        frm=ttk.Frame(self,padding=20); frm.pack(fill='x')
        ttk.Entry(frm,textvariable=self.src).pack(side='left',fill='x',expand=True,padx=(0,8))
        ttk.Button(frm,text='Choisir le CSV',command=self.choose).pack(side='left')
        self.go=ttk.Button(self,text='Traiter le fichier',command=self.start); self.go.pack(pady=5)
        ttk.Label(self,textvariable=self.status,wraplength=700).pack(pady=10)
        self.pb=ttk.Progressbar(self,mode='indeterminate',length=620); self.pb.pack(pady=5)
        box=ttk.LabelFrame(self,text='Règles V1',padding=14); box.pack(fill='both',expand=True,padx=20,pady=10)
        rules=('• Le fichier source doit correspondre exactement au DE Cartegie de référence (50 colonnes).\n'
               '• Ajout en 51e colonne : DATE_CONSENTEMENT_TELEMARKETING.\n'
               '• Valeur = Date dernière inscription. Aucun filtre selon l’ancienneté.\n'
               '• Contrôles : email, CP, téléphone fixe/mobile, date inscription, structure des lignes.\n'
               '• Les données suspectes ne sont pas supprimées : elles sont listées dans le rapport d’anomalies.\n'
               '• Les lignes structurellement illisibles sont isolées dans les anomalies pour éviter un fichier décalé.')
        ttk.Label(box,text=rules,justify='left',wraplength=680).pack(anchor='w')
        self.after(150,self.poll)
    def choose(self):
        p=filedialog.askopenfilename(filetypes=[('Fichiers CSV','*.csv'),('Tous les fichiers','*.*')])
        if p:self.src.set(p)
    def start(self):
        p=self.src.get().strip()
        if not p or not Path(p).exists(): messagebox.showerror('Fichier','Choisis un fichier CSV valide.'); return
        out=filedialog.asksaveasfilename(defaultextension='.csv',initialfile=Path(p).stem+'_CARTEGIE.csv',filetypes=[('CSV','*.csv')])
        if not out:return
        self.go.config(state='disabled'); self.pb.start(10); self.status.set('Traitement en cours…')
        def work():
            try:self.q.put(('done',process(p,out,self.q),out))
            except Exception as e:self.q.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()
    def poll(self):
        try:
            while True:
                m=self.q.get_nowait()
                if m[0]=='progress': self.status.set(f'Traitement en cours… {m[1]:,} lignes lues'.replace(',',' '))
                elif m[0]=='done':
                    self.pb.stop(); self.go.config(state='normal'); c,rep,ano=m[1]; out=m[2]
                    self.status.set(f'Terminé : {c["lignes"]:,} lignes analysées.'.replace(',',' '))
                    messagebox.showinfo('Terminé',f'Fichier Cartegie créé :\n{out}\n\nRapport :\n{rep}\n\nAnomalies :\n{ano}')
                elif m[0]=='error': self.pb.stop(); self.go.config(state='normal'); self.status.set('Erreur : '+m[1]); messagebox.showerror('Erreur',m[1])
        except queue.Empty: pass
        self.after(150,self.poll)

if __name__=='__main__': App().mainloop()
