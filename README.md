# Cartegie Mapper v1.0.8

- Entrées acceptées : DE standard 50 colonnes (virgule, point-virgule, tabulation) et export Lesmalices 51 colonnes comportant les deux champs `sante/beaute` et `sante/beauté`.
- Mapping Lesmalices : `sante/beauté` est prioritaire ; si vide, reprend `sante/beaute`. Les conflits entre valeurs renseignées sont tracés dans les anomalies sans fusion silencieuse.
- Sortie Cartegie **toujours** : 51 colonnes (50 du DE standard + `DATE_CONSENTEMENT_TELEMARKETING`), séparées par virgules, **chaque champ entre guillemets** (y compris champs vides).
- Dates des champs de date identifiés normalisées au format `AAAA-MM-JJ HH:MM:SS` lorsqu'elles sont reconnues. Les dates non reconnues sont conservées et doivent être vérifiées.
- Toutes les règles de nettoyage CP/téléphones et de contrôle de structure v1.0.7 conservées.

## Mise à jour GitHub
Décompresser l'archive et remplacer `cartegie_cleaner.py`, `README.md` et `.github/workflows/build-release.yml` à la racine du dépôt. Dans Actions, lancer le workflow avec `v1.0.8`, puis télécharger l'EXE dans Releases.

## Vérifications
Avant livraison, vérifier le rapport de contrôle et contrôler le CSV produit sur un échantillon représentatif, notamment les dates et les champs adresse contenant des virgules.
