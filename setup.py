import os
from setuptools import find_packages, setup

def load_requirements(filename: str) -> list:
    """
    Charge les requirements depuis un fichier, en ignorant les lignes vides, les
    commentaires (#..., en ligne ou pleine ligne) et les directives '-r' (pour
    éviter les boucles récursives).
    """
    if not os.path.exists(filename):
        return []

    with open(filename, "r") as f:
        content = f.readlines()

    requirements = []
    for line in content:
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-r") and "git+" not in line:
            requirements.append(line)
    return requirements

setup(
    name='berlue',
    version="0.0.1",
    description="Projet template MLOps",
    author="Your Name", # TODO: Mettre à jour le nom de l'auteur

    # Trouve automatiquement les packages mais exclut le dossier tests de la production
    packages=find_packages(exclude=["tests", "tests.*"]),

    # Dépendances de production principales
    install_requires=load_requirements("requirements.txt"),

    # Dépendances de développement optionnelles
    extras_require={
        "dev": load_requirements("requirements_dev.txt")
    },
)
