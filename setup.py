from pathlib import Path

from setuptools import find_namespace_packages, setup


README = Path(__file__).with_name("README.md").read_text(encoding="utf-8")


setup(
    name="coda-cli",
    version="0.1.0",
    description="Stateful CLI for Coda docs, pages, tables, and rows",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/dishant0406/coda-cli",
    author="Dishant",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    include_package_data=True,
    install_requires=["click>=8,<9"],
    entry_points={
        "console_scripts": [
            "coda-cli=cli_anything.coda.coda_cli:main",
            "cli-anything-coda=cli_anything.coda.coda_cli:main",
        ]
    },
    python_requires=">=3.9",
)
