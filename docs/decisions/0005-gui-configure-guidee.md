# 0005 — Écran Configure guidé (2026-10-27)

## Contexte
L'écran Configure de la GUI était généré depuis le schéma pydantic : libellés dérivés des
noms de clés, aide en infobulle seulement (et absente pour ~15 champs), listes en texte libre
sans suggestion, toutes les sections au même niveau, messages d'erreur pydantic bruts. Un
nouvel utilisateur ne savait ni quoi saisir ni l'effet de chaque champ.

## Décision
- **Catalogue de champs** `scilex/gui/services/field_catalog.py` : pour chaque chemin
  (`filters.item_types`…) un libellé rédigé, une aide, un exemple/placeholder, des
  suggestions et un niveau (`essential` / `advanced`). Un test garantit que **chaque champ du
  schéma** a une entrée : un nouveau champ sans aide fait échouer la suite.
- **Aide toujours visible** sous le champ (plus d'infobulle), avec la valeur par défaut.
- **Autocomplétion** : listes connues (types de document, modèles LLM, sources de citations)
  en sélection multiple avec saisie libre ; mots-clés suggérés depuis les templates de
  domaine ; date via un sélecteur.
- **Deux niveaux** : « Essentials » (nom, preset, mots-clés, années, sources) ouvert, puis
  « Filters » et un bloc « Advanced settings » replié.
- **Aides au jugement** calculées dans `config_editor` (sans UI, testées) : estimation du
  nombre de requêtes (mêmes règles que `queryCompositor`), avertissements de dépendances
  (filtre de citations sans récupération, clé manquante pour une source ou une option),
  messages d'erreur reformulés avec le libellé du champ.
- Années inversées : erreur claire, la valeur n'est plus convertie en chaîne.
- **Interface en anglais**, pas de localisation : hors périmètre (public international,
  coût de maintenance de deux langues pour un mainteneur seul).
- La perte des commentaires YAML à l'enregistrement est conservée (pas de dépendance
  `ruamel`), mais la mention est déplacée dans l'éditeur brut, là où elle concerne
  l'utilisateur.

## Conséquences
- Tout nouveau champ de `scilex.yml` doit être ajouté au catalogue (étape 6 de « Adding a
  new config option »).
- Les marqueurs de test existants (`field-<chemin>`, `config-save`…) sont conservés.
