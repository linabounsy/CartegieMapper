import csv, re, threading, queue, unicodedata
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

VERSION = "1.0.5"

EXPECTED = ['IdBase','IdUser','Adresse EMail','email sha 256','Date dernière inscription','Dernière provenance','Civilité','Nom','Prénom','Adresse','Ville','CP','Pays','Date de naissance','Tel Fixe','Tel Mobile','tel_verif','Dernière ouverture (MARKETING)','Date Dernier Clic','statut_immo','CSP','RGPD Consentement ouverture','alcool','animaux','association','assurance','auto','banque','beauté','bonreduc','crédit/rac','defiscalisation/finance','eshopping','formation','hightech','Immobilier','isolation','jardin','jeuxconcours','loisirs','maman','minceur','mutuelle','newsletter','panel','sante/beauté','santé/bien-être','senior','travaux','Voyages']
NEWCOL = 'DATE_CONSENTEMENT_TELEMARKETING'
EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
PARASITES = {"#VALEUR!", "#VALUE!", "#N/A", "#N/A!", "#REF!", "#NOM?", "#NAME?"}

def norm_header(s):
    s = unicodedata.normalize("NFKC", (s or "").strip())
    return " ".join(s.casefold().split())

EXPECTED_NORM = [norm_header(x) for x in EXPECTED]

def detect_encoding(path):
    with open(path, "rb") as f:
        raw = f.read(200000)
    if raw.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    try:
        raw.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        return 'latin1'

def clean_value(v):
    if v is None:
        return ""
    x = v.strip()
    if x.upper() in PARASITES:
        return ""
    return v

def norm_phone(v):
    return re.sub(r'[^0-9+]','',v or '')

def valid_phone(v):
    if not (v or '').strip():
        return True
    x = norm_phone(v)
    if x.startswith('+33'):
        x = '0' + x[3:]
    return bool(re.fullmatch(r'0[1-9]\d{8}', x))

def clean_cp(v):
    """Nettoie le CP sans inventer de valeur : nan -> vide ; 4 chiffres -> zéro devant."""
    x = (v or '').strip()
    if not x or x.casefold() == 'nan':
        return '', 'VIDE_NAN' if x else None
    if re.fullmatch(r'\d{4}', x):
        return '0' + x, 'ZERO_AJOUTE'
    return v, None

def norm_city(v):
    """Normalise une ville pour comparaison interne (accents/casse/espaces)."""
    s = unicodedata.normalize("NFKD", (v or "").strip())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^A-Za-z0-9]+", " ", s).strip().casefold()
    return " ".join(s.split())

def cp_00_candidate(v):
    """00750 -> 75000, 00130 -> 13000. Ne propose rien hors motif 00xxx."""
    x = (v or "").strip()
    if re.fullmatch(r"00\d{3}", x):
        return x[2:] + "00"
    return None

def valid_cp(v):
    if not (v or '').strip():
        return True
    x = v.strip().upper()
    # Métropole + Corse + DOM/COM (97xxx / 98xxx).
    return bool(re.fullmatch(r'(?:0[1-9]|[1-8]\d|9[0-8]|2[AB])\d{3}', x))

def clean_phone_fr(v):
    """Normalise les numéros français ; vide les formats manifestement internationaux hors France."""
    raw = (v or '').strip()
    if not raw:
        return v, None
    compact = re.sub(r'[^0-9+]', '', raw)
    if compact.startswith('+33'):
        candidate = '0' + compact[3:]
        if re.fullmatch(r'0[1-9]\d{8}', candidate):
            return candidate, 'FR_NORMALISE' if candidate != raw else None
    if compact.startswith('0033'):
        candidate = '0' + compact[4:]
        if re.fullmatch(r'0[1-9]\d{8}', candidate):
            return candidate, 'FR_NORMALISE' if candidate != raw else None
    if re.fullmatch(r'0[1-9]\d{8}', compact):
        return compact, 'FR_NORMALISE' if compact != raw else None
    # Hors France explicite (+XX / 00XX), ou numéro long sans 0 initial (ex. 31..., 32..., 61...).
    if (compact.startswith('+') and not compact.startswith('+33')) or \
       (compact.startswith('00') and not compact.startswith('0033')) or \
       (len(re.sub(r'\D', '', compact)) > 10 and not compact.startswith('0')):
        return '', 'INTERNATIONAL_VIDE'
    # Le fichier est France uniquement : tout numéro restant qui n'est pas un 0XXXXXXXXX valide est vidé.
    return '', 'INVALIDE_VIDE'

def valid_date(v):
    if not (v or '').strip():
        return True
    s = v.strip()
    for fmt in (
        '%Y-%m-%d %H:%M:%S','%Y-%m-%d',
        '%d/%m/%Y %H:%M:%S','%d/%m/%Y',
        '%d-%m-%Y %H:%M:%S','%d-%m-%Y'
    ):
        try:
            datetime.strptime(s, fmt)
            return True
        except ValueError:
            pass
    return False

def score_row(row):
    """Score de cohérence pour choisir une réparation prudente."""
    if len(row) != 50:
        return -999
    score = 0
    if not row[2].strip() or EMAIL_RE.match(row[2].strip()): score += 4
    if valid_date(row[4]): score += 3
    if valid_cp(row[11]): score += 2
    if valid_phone(row[14]): score += 2
    if valid_phone(row[15]): score += 2
    return score

def repair_extra_columns(row):
    """
    Les exports Mindbaz peuvent contenir des virgules/guillemets parasites,
    principalement dans les champs texte. On ne décale jamais arbitrairement
    les colonnes métier : on teste la fusion de l'excédent dans les champs
    texte les plus plausibles et on ne conserve qu'une réparation cohérente.
    """
    if len(row) == 50:
        return row, None
    if len(row) < 50:
        return None, None

    excess = len(row) - 50
    candidates = []
    # Champs texte libres les plus susceptibles de contenir une virgule parasite.
    for idx in (9, 10, 8, 7, 5):  # Adresse, Ville, Prénom, Nom, Provenance
        end = idx + excess + 1
        if end > len(row):
            continue
        candidate = row[:idx] + [",".join(row[idx:end])] + row[end:]
        if len(candidate) == 50:
            candidates.append((score_row(candidate), idx, candidate))

    if not candidates:
        return None, None
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0]
    # Exige une cohérence minimale sur les colonnes structurantes.
    if best[0] < 7:
        return None, None
    return best[2], EXPECTED[best[1]]

def process(src, out, logq):
    enc = detect_encoding(src)

    # Passe 1 : construit une référence Ville -> CP valides à partir du fichier lui-même.
    # Elle permet de corriger un 00xxx uniquement si le CP candidat existe déjà pour cette ville.
    city_cps = {}
    with open(src, 'r', encoding=enc, newline='') as fref:
        rref = csv.reader(fref)
        try:
            href = next(rref)
        except StopIteration:
            raise ValueError('Le fichier est vide.')
        if [norm_header(x) for x in href] != EXPECTED_NORM:
            raise ValueError('DE Cartegie non conforme.')
        for nref, raw in enumerate(rref, start=1):
            rr, _ = repair_extra_columns(raw)
            if rr is None:
                continue
            city = norm_city(rr[10])
            cp0, _ = clean_cp(clean_value(rr[11]))
            cp = (cp0 or '').strip().upper()
            if city and valid_cp(cp):
                city_cps.setdefault(city, set()).add(cp)
            if nref % 100000 == 0:
                logq.put(('phase1', nref))

    counts = {
        'lignes_lues': 0,
        'lignes_exportees': 0,
        'lignes_reparees_structure': 0,
        'lignes_rejetees_structure': 0,
        'valeurs_parasites_videes': 0,
        'cp_nan_vides': 0,
        'cp_4_chiffres_corriges': 0,
        'cp_00_corriges_ville_confirmee': 0,
        'cp_00_vides_sans_correspondance_ville': 0,
        'telephones_internationaux_vides': 0,
        'telephones_fr_normalises': 0,
        'telephones_invalides_vides': 0,
        'emails_invalides': 0,
        'cp_invalides_vides': 0,
        'tel_fixe_invalides_non_vides': 0,
        'tel_mobile_invalides_non_vides': 0,
        'dates_inscription_invalides_non_vides': 0,
        'dates_consentement_renseignees': 0,
    }

    anomaly_file = Path(out).with_name(Path(out).stem + '_ANOMALIES.csv')
    reject_file = Path(out).with_name(Path(out).stem + '_REJETS_STRUCTURE.csv')
    report = Path(out).with_name(Path(out).stem + '_RAPPORT.txt')

    with open(src, 'r', encoding=enc, newline='') as fi, \
         open(out, 'w', encoding=enc, newline='') as fo, \
         open(anomaly_file, 'w', encoding='utf-8-sig', newline='') as fa, \
         open(reject_file, 'w', encoding='utf-8-sig', newline='') as fr:

        reader = csv.reader(fi)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError('Le fichier est vide.')

        if [norm_header(x) for x in header] != EXPECTED_NORM:
            details = []
            for i in range(max(len(header), 50)):
                got = header[i] if i < len(header) else '<MANQUANT>'
                exp = EXPECTED[i] if i < 50 else '<EN TROP>'
                if i >= len(header) or i >= 50 or norm_header(got) != norm_header(exp):
                    details.append(f'colonne {i+1}: attendu "{exp}" / reçu "{got}"')
            raise ValueError(
                'DE Cartegie non conforme.\n'
                f'Colonnes lues : {len(header)} / attendu : 50.\n' +
                '\n'.join(details[:12])
            )

        writer = csv.writer(fo, quoting=csv.QUOTE_MINIMAL)
        aw = csv.writer(fa, delimiter=';')
        rw = csv.writer(fr, delimiter=';')
        writer.writerow(header + [NEWCOL])
        aw.writerow(['LIGNE_SOURCE','TYPE','COLONNE','VALEUR'])
        rw.writerow(['LIGNE_SOURCE','NB_CHAMPS','LIGNE_PARSE'])

        for source_line, raw_row in enumerate(reader, start=2):
            counts['lignes_lues'] += 1

            row, repaired_field = repair_extra_columns(raw_row)
            if row is None:
                counts['lignes_rejetees_structure'] += 1
                rw.writerow([source_line, len(raw_row), repr(raw_row)])
                if counts['lignes_lues'] % 50000 == 0:
                    logq.put(('progress', counts['lignes_lues']))
                continue

            if repaired_field:
                counts['lignes_reparees_structure'] += 1
                aw.writerow([source_line, 'STRUCTURE_REPAREE', repaired_field,
                             f'{len(raw_row)} champs -> 50'])

            # #VALEUR! et équivalents deviennent vides, sans supprimer la ligne.
            cleaned = []
            for idx, val in enumerate(row):
                nv = clean_value(val)
                if nv == "" and (val or "").strip().upper() in PARASITES:
                    counts['valeurs_parasites_videes'] += 1
                    aw.writerow([source_line, 'VALEUR_PARASITE_VIDEE', header[idx], val])
                cleaned.append(nv)
            row = cleaned

            # CP : nan -> vide ; 4 chiffres -> ajout d'un zéro devant.
            new_cp, cp_action = clean_cp(row[11])
            if cp_action == 'VIDE_NAN':
                counts['cp_nan_vides'] += 1
                aw.writerow([source_line, 'CP_NAN_VIDE', header[11], row[11]])
            elif cp_action == 'ZERO_AJOUTE':
                counts['cp_4_chiffres_corriges'] += 1
                aw.writerow([source_line, 'CP_4_CHIFFRES_CORRIGE', header[11], f'{row[11]} -> {new_cp}'])
            row[11] = new_cp

            # CP 00xxx : correction uniquement si la ville confirme le CP candidat dans les CP valides du fichier.
            cand = cp_00_candidate(row[11])
            if cand:
                city_key = norm_city(row[10])
                if city_key and cand in city_cps.get(city_key, set()):
                    old_cp = row[11]
                    row[11] = cand
                    counts['cp_00_corriges_ville_confirmee'] += 1
                    aw.writerow([source_line, 'CP_00_CORRIGE_VILLE_CONFIRMEE', header[11], f'{old_cp} -> {cand} | Ville={row[10]}'])
                else:
                    old_cp = row[11]
                    row[11] = ''
                    counts['cp_00_vides_sans_correspondance_ville'] += 1
                    aw.writerow([source_line, 'CP_00_VIDE_SANS_CORRESPONDANCE_VILLE', header[11], f'{old_cp} -> VIDE | Ville={row[10]} | candidat={cand}'])

            # Téléphones : conservation France, normalisation +33/0033, vidage des internationaux et invalides.
            for idx in (14, 15):
                old_phone = row[idx]
                new_phone, phone_action = clean_phone_fr(old_phone)
                if phone_action == 'INTERNATIONAL_VIDE':
                    counts['telephones_internationaux_vides'] += 1
                    aw.writerow([source_line, 'TEL_INTERNATIONAL_VIDE', header[idx], old_phone])
                elif phone_action == 'FR_NORMALISE':
                    counts['telephones_fr_normalises'] += 1
                elif phone_action == 'INVALIDE_VIDE':
                    counts['telephones_invalides_vides'] += 1
                    aw.writerow([source_line, 'TEL_INVALIDE_VIDE', header[idx], old_phone])
                row[idx] = new_phone

            email = row[2].strip()
            cp = row[11].strip()
            fixe = row[14].strip()
            mob = row[15].strip()
            dt = row[4].strip()

            if email and not EMAIL_RE.match(email):
                counts['emails_invalides'] += 1
                aw.writerow([source_line,'EMAIL_INVALIDE',header[2],email])
            if cp and not valid_cp(cp):
                # Dernier filet de sécurité Cartegie : un CP restant invalide est vidé, jamais inventé.
                counts['cp_invalides_vides'] += 1
                aw.writerow([source_line,'CP_INVALIDE_VIDE',header[11],f'{cp} -> VIDE | Ville={row[10]}'])
                row[11] = ''
                cp = ''
            if fixe and not valid_phone(fixe):
                counts['tel_fixe_invalides_non_vides'] += 1
                aw.writerow([source_line,'TEL_FIXE_INVALIDE',header[14],fixe])
            if mob and not valid_phone(mob):
                counts['tel_mobile_invalides_non_vides'] += 1
                aw.writerow([source_line,'TEL_MOBILE_INVALIDE',header[15],mob])
            if dt and not valid_date(dt):
                counts['dates_inscription_invalides_non_vides'] += 1
                aw.writerow([source_line,'DATE_INSCRIPTION_INVALIDE',header[4],dt])

            if dt:
                counts['dates_consentement_renseignees'] += 1

            writer.writerow(row + [dt])
            counts['lignes_exportees'] += 1

            if counts['lignes_lues'] % 50000 == 0:
                logq.put(('progress', counts['lignes_lues']))

    with open(report, 'w', encoding='utf-8') as f:
        f.write(f'CARTEGIE MAPPER V{VERSION} - RAPPORT DE CONTROLE\n')
        f.write('=' * 50 + '\n')
        f.write(f'Fichier source : {src}\n')
        f.write(f'Fichier produit : {out}\n')
        f.write(f'Encodage : {enc}\n\n')
        f.write('DE : 50 colonnes Cartegie + DATE_CONSENTEMENT_TELEMARKETING en dernière colonne.\n')
        f.write('Règle : DATE_CONSENTEMENT_TELEMARKETING = Date dernière inscription.\n')
        f.write('Aucun filtre selon ancienneté télémarketing.\n')
        f.write('#VALEUR! / #VALUE! et erreurs Excel équivalentes : remplacées par vide.\n')
        f.write('CP : nan -> vide ; 4 chiffres -> ajout d’un 0 devant ; 97xxx/98xxx acceptés ; 00xxx corrigé si la ville confirme le CP candidat ; sinon CP vidé ; tout CP restant invalide est vidé.\n')
        f.write('Téléphones : numéros internationaux et formats invalides vidés ; +33/0033 français normalisés en 0XXXXXXXXX.\n')
        f.write('Lignes avec colonnes excédentaires : réparation prudente si cohérence vérifiable ; sinon rejet tracé.\n\n')
        for k, v in counts.items():
            f.write(f'{k.replace("_"," ").capitalize()} : {v:,}\n'.replace(',',' '))
        f.write('\nIMPORTANT : les anomalies métier (email/CP/téléphone/date) sont signalées mais ne suppriment pas la ligne.\n')

    return counts, str(report), str(anomaly_file), str(reject_file)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'Cartegie Mapper v{VERSION}')
        self.geometry('790x570')
        self.minsize(720, 510)
        self.q = queue.Queue()
        self.src = tk.StringVar()
        self.status = tk.StringVar(value='Sélectionne un export Mindbaz Cartegie.')

        ttk.Label(self, text=f'Cartegie Mapper v{VERSION}',
                  font=('Segoe UI',20,'bold')).pack(pady=(20,4))
        ttk.Label(self, text='DE Cartegie figé • gros fichiers • nettoyage + contrôle').pack()

        frm = ttk.Frame(self, padding=20)
        frm.pack(fill='x')
        ttk.Entry(frm, textvariable=self.src).pack(side='left', fill='x', expand=True, padx=(0,8))
        ttk.Button(frm, text='Choisir le CSV', command=self.choose).pack(side='left')

        self.go = ttk.Button(self, text='Traiter le fichier', command=self.start)
        self.go.pack(pady=5)
        ttk.Label(self, textvariable=self.status, wraplength=730).pack(pady=10)
        self.pb = ttk.Progressbar(self, mode='indeterminate', length=650)
        self.pb.pack(pady=5)

        box = ttk.LabelFrame(self, text='Règles V1.0.5', padding=14)
        box.pack(fill='both', expand=True, padx=20, pady=10)
        rules = (
            '• DE source Cartegie : 50 colonnes, comparaison tolérante à la casse et aux espaces.\n'
            '• Ajout : DATE_CONSENTEMENT_TELEMARKETING = Date dernière inscription.\n'
            '• Aucun filtre d’ancienneté télémarketing.\n'
            '• CP : nan vide ; 4 chiffres = 0 devant ; 97xxx/98xxx acceptés ; 00xxx corrigé si la ville confirme le CP candidat ; sinon vidé ; tout CP restant invalide est vidé.\n'
            '• Téléphones internationaux ou invalides : cellule vidée ; +33/0033 français normalisés.\n'
            '• #VALEUR! / #VALUE! et erreurs Excel équivalentes sont vidées.\n'
            '• Les décalages dus à des virgules/guillemets parasites sont réparés seulement si la cohérence est vérifiable.\n'
            '• Les lignes impossibles à reconstruire sont isolées dans REJETS_STRUCTURE, jamais perdues silencieusement.\n'
            '• Les anomalies email/CP/téléphone/date sont signalées mais la ligne reste exportée.\n'
            '• Traitement en streaming : adapté aux fichiers de plusieurs millions de lignes.'
        )
        ttk.Label(box, text=rules, justify='left', wraplength=710).pack(anchor='w')
        self.after(150, self.poll)

    def choose(self):
        p = filedialog.askopenfilename(filetypes=[('Fichiers CSV','*.csv'),('Tous les fichiers','*.*')])
        if p:
            self.src.set(p)

    def start(self):
        p = self.src.get().strip()
        if not p or not Path(p).exists():
            messagebox.showerror('Fichier','Choisis un fichier CSV valide.')
            return
        out = filedialog.asksaveasfilename(
            defaultextension='.csv',
            initialfile=Path(p).stem + '_CARTEGIE.csv',
            filetypes=[('CSV','*.csv')]
        )
        if not out:
            return
        self.go.config(state='disabled')
        self.pb.start(10)
        self.status.set('Traitement en cours…')

        def work():
            try:
                self.q.put(('done', process(p, out, self.q), out))
            except Exception as e:
                self.q.put(('error', str(e)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == 'phase1':
                    self.status.set(f'Passe 1/2 : apprentissage Ville/CP… {m[1]:,} lignes lues'.replace(',',' '))
                elif m[0] == 'progress':
                    self.status.set(f'Passe 2/2 : traitement… {m[1]:,} lignes lues'.replace(',',' '))
                elif m[0] == 'done':
                    self.pb.stop()
                    self.go.config(state='normal')
                    c, rep, ano, rej = m[1]
                    out = m[2]
                    self.status.set(
                        f'Terminé : {c["lignes_lues"]:,} lues / {c["lignes_exportees"]:,} exportées / '
                        f'{c["lignes_reparees_structure"]:,} réparées / {c["lignes_rejetees_structure"]:,} rejetées.'
                        .replace(',',' ')
                    )
                    messagebox.showinfo(
                        'Terminé',
                        f'Fichier Cartegie :\n{out}\n\nRapport :\n{rep}\n\nAnomalies :\n{ano}\n\nRejets structure :\n{rej}'
                    )
                elif m[0] == 'error':
                    self.pb.stop()
                    self.go.config(state='normal')
                    self.status.set('Erreur : ' + m[1])
                    messagebox.showerror('Erreur', m[1])
        except queue.Empty:
            pass
        self.after(150, self.poll)

if __name__ == '__main__':
    App().mainloop()
