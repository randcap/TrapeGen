from setuptools import find_packages, setup


setup(
    name="trapegen",
    version="0.1.0",
    python_requires=">=3.10",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "numpy>=2.2.6,<3",
        "scipy>=1.15.3,<2",
        "trimesh>=4.12.2,<5",
        "shapely>=2.1.2,<3",
        "mapbox-earcut>=2.0.0,<3",
        "manifold3d>=3.4.1,<4",
        "matplotlib>=3.10.8,<4",
        "cadquery-ocp-novtk==7.8.1.1",
    ],
    entry_points={"console_scripts": ["trapegen=trapegen.cli:main"]},
)
