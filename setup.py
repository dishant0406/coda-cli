from setuptools import find_namespace_packages, setup


setup(
    name="cli-anything-coda",
    version="0.1.0",
    description="CLI-Anything harness for Coda derived from the coda-mcp API surface",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    include_package_data=True,
    install_requires=["click>=8,<9"],
    entry_points={
        "console_scripts": [
            "cli-anything-coda=cli_anything.coda.coda_cli:main",
        ]
    },
    python_requires=">=3.9",
)
