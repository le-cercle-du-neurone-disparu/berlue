# description des données HaluEval

## premier apperçu

pour comprendre ce [notebook](data-HaluEval.ipynb)  :
 import de pandas et l'url de Github RUCAIBox ( au dessus)
fichier en json.
une fois traité : le fichier donne

une colonne affirmation('knowledge' -extrait encyclopédie ou autre-)

une colonne de question ('Question') sur le sujet

une colonne 'answer' la réponse attendue ou erronée

une colonne 'hallucinated' en Booléen qui vérifie si la réponse est bonne (hallucinated : False) ou fausse (hallucinated : True) avec une égalité.

Une ligne sur deux, la réponse est True.
