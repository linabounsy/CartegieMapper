# Cartegie Mapper v1.0.9

Conserve toutes les règles de la v1.0.8, avec correction des numéros français dont le zéro initial a été perdu à l'export.

- Un numéro de 9 chiffres commençant par 1 à 9 est converti en numéro français à 10 chiffres en préfixant `0`, puis conservé.
- Les numéros internationaux hors France et les formats restant invalides sont vidés, sans supprimer de contact.
- Le rapport inclut le compteur `Telephones zero initial restaure`.
- Format Cartegie : 51 colonnes, séparateur virgule, guillemets systématiques, dates normalisées.
- Mapping Lesmalices : `sante/beauté` prioritaire, repli sur `sante/beaute` si vide, conflits tracés.

**Contrôle recommandé** : examiner le rapport et un échantillon de téléphones restaurés avant livraison.
