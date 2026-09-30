# Cartegie Cleaner

Petit outil Windows pour retraiter les exports Mindbaz destinés à Cartegie.

## Règle métier V1

Le dessin d'enregistrement source est celui du fichier Cartegie de référence fourni (50 colonnes).
La sortie conserve ces 50 colonnes et ajoute en dernière position :

`DATE_CONSENTEMENT_TELEMARKETING`

Sa valeur est reprise depuis `Date dernière inscription`. Aucun filtre d'ancienneté n'est appliqué aux numéros de téléphone.

## Contrôles

- conformité du DE source ;
- structure des lignes CSV ;
- format email ;
- code postal ;
- téléphone fixe et mobile ;
- date d'inscription ;
- comptage des lignes et des dates de consentement renseignées.

Les anomalies de contenu sont signalées mais ne provoquent pas la suppression du contact. Une ligne dont la structure est inexploitable n'est pas injectée dans le fichier livré afin d'éviter tout décalage de colonnes ; elle est tracée dans le fichier d'anomalies et dans le rapport.

## Utilisation

1. Lance `Cartegie_Cleaner.exe`.
2. Clique sur **Choisir le CSV**.
3. Sélectionne l'export Mindbaz Cartegie.
4. Clique sur **Traiter le fichier**.
5. Choisis le nom du fichier de sortie.

L'outil crée également :

- `*_RAPPORT.txt` : synthèse des contrôles ;
- `*_ANOMALIES.csv` : détail des anomalies.

## Générer l'EXE avec GitHub

Dépose tout ce projet dans un nouveau repository GitHub. Ensuite ouvre **Actions** et lance le workflow **Build Windows EXE** avec **Run workflow**. L'EXE sera disponible dans les **Artifacts** du workflow sous le nom `Cartegie-Cleaner-Windows`.

À chaque push sur `main`, GitHub reconstruit également l'exécutable.
