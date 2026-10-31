# Simco Trader

Tableau de bord d'achat-revente pour **Sim Companies, royaume Entrepreneurs (R2)**.

Toutes les 30 minutes, GitHub relève le prix le plus bas de chaque objet et de chaque qualité sur le marché. Une fois par jour, il recharge aussi l'historique journalier sur 90 jours (prix moyen, plus bas, plus haut, volume). La page web classe ensuite les objets **vendus en ce moment sous leur prix habituel**, en tenant compte des frais de vente, du volume échangé et de la façon dont le prix a rebondi par le passé.

Les données viennent de l'API publique SimcoTools. L'outil ne fait que lire et conseiller : les achats et les ventes se font à la main dans le jeu.

## Mise en place (une seule fois, environ 10 minutes)

1. **Crée un compte GitHub** sur https://github.com si tu n'en as pas.
2. **Crée un dépôt** : bouton « New repository », nom `simco-trader`, coche **Public** (obligatoire pour que la page web soit gratuite), puis « Create repository ».
3. **Envoie les fichiers** : sur la page du dépôt, « uploading an existing file », puis glisse le contenu du dossier dézippé (`collector`, `site`, `README.md` et le dossier `.github`), puis « Commit changes ».
   - Si le dossier `.github` ne passe pas (il est caché sur Mac), fais « Add file → Create new file », tape le nom `.github/workflows/collecte.yml`, colle le contenu du fichier `collecte.yml`, puis « Commit changes ».
4. **Active la page web** : « Settings → Pages », et dans « Build and deployment → Source », choisis **GitHub Actions**.
5. **Lance la première collecte** : onglet « Actions » (accepte l'activation si GitHub la demande), clique sur « Collecte des prix » à gauche, puis sur « Run workflow ». Le premier passage dure environ 10 minutes, parce qu'il charge 90 jours d'historique pour chaque objet. Les passages suivants prennent moins d'une minute, sauf le rechargement quotidien.
6. **Ouvre ton tableau de bord** : `https://TON-PSEUDO.github.io/simco-trader/`. Le lien exact est affiché dans « Settings → Pages ». Mets-le en favori, il marche aussi sur téléphone.

Ensuite, la collecte tourne toute seule, même quand ton PC est éteint.

## À savoir

- **Royaume** : la ligne `REALM: "1"` dans `.github/workflows/collecte.yml` correspond à Entrepreneurs (R2). Mets `"0"` pour Magnates (R1).
- **Frais de vente** : 4 % par défaut, modifiable en haut de la page. Vérifie le taux affiché dans le jeu quand tu mets un objet en vente.
- **Quantité au prix le plus bas** : la page affiche l'offre la moins chère, mais il peut n'y avoir que quelques unités à ce prix. Vérifie toujours dans le jeu avant d'acheter.
- **Meilleures heures d'achat et de vente** : elles apparaissent après 3 jours de relevés.
- **Pause automatique** : GitHub suspend les tâches planifiées d'un dépôt public sans activité pendant 60 jours. Si la page affiche « il y a X h », va dans « Actions » et réactive le workflow.
- Le site est public (n'importe qui ayant le lien peut le voir), mais il ne contient que des prix du marché, rien sur ton entreprise.
- Rien n'est garanti : les prix passés ne prédisent pas l'avenir. Commence avec de petites quantités pour vérifier que les reventes se passent comme prévu.
