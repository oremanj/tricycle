from setuptools import setup, find_packages

exec(open("tricycle/_version.py", encoding="utf-8").read())

LONG_DESC = open("README.rst", encoding="utf-8").read()

setup(
    name="tricycle",
    version=__version__,
    description="Experiemntal extensions for Trio, the friendly async I/O library",
    url="https://github.com/oremanj/tricycle",
    long_description=LONG_DESC,
    author="Joshua Oreman",
    author_email="oremanj@gmail.com",
    license="MIT -or- Apache License 2.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=["trio >= 0.15.0", "trio-typing >= 0.5.0"],
    keywords=["async", "trio"],
    python_requires=">=3.6",
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
        "Framework :: Trio",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: Implementation :: CPython",
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
    ],
)
