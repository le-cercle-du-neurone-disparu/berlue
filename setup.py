import os
from setuptools import find_packages, setup

def load_requirements(filename: str) -> list:
    """
    Load requirements from a file, ignoring empty lines
    and '-r' directives (to avoid recursive loops).
    """
    if not os.path.exists(filename):
        return []

    with open(filename, "r") as f:
        content = f.readlines()

    requirements = [
        x.strip() for x in content
        if x.strip() and not x.startswith("-r") and "git+" not in x
    ]
    return requirements

setup(
    name='berlue',
    version="0.0.1",
    description="MLOps template project",
    author="Your Name", # TODO: Update author name

    # Automatically find packages but exclude the tests folder from production
    packages=find_packages(exclude=["tests", "tests.*"]),

    # Core production dependencies
    install_requires=load_requirements("requirements.txt"),

    # Optional development dependencies
    extras_require={
        "dev": load_requirements("requirements_dev.txt")
    },
)
