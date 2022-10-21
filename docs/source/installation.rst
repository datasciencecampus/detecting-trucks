.. highlight:: shell

============
Installation
============


From source
------------

The source for the truck detection project is composed of a series of python Scripts
and can be downloaded from the
`Github Repo <https://github.com/datasciencecampus/ek_hub_faster_economic_indicators/tree/master/trucks>`_.

Clone the repository:

.. code-block:: bash

    git clone <insert link here>

Dependencies
------------

Conda environment (recommended)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The **recommended** way to install the required dependencies is to build a **Conda
environment** from the provided `environment.yml` file.

In a terminal with Conda enabled, such as Anaconda Prompt (recommended if using a
Windows device), change directory into the repository root and run the following:

.. code-block:: bash

   conda env create -f environment.yml

After installing the required packages (which may take a few minutes), this
should have created an environment called "trucks_env". Activate this
by running:

.. code-block:: bash

   conda activate trucks_env

Pip install from requirements.txt (not recommended)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

*Alternatively*, the requirements can be installed using a virtual environment
and pip installing from the provided `requirements.txt`. This option is **not
recommended** however if using a Windows machine as a number of the required
geospatial packages (such as `Fiona` and `rasterio`) are non-trivial to install
on Windows.

If installing this way:

Change directory a level above and create a directory named `virtual_envs`:

.. code-block:: bash

    cd ../

.. code-block:: bash

    mkdir virtual_envs

.. code-block:: bash

    cd virtual_envs/

Spawn a virtual environment using `virtualenv` (install it with `python3 -m pip install --user virtualenv` if not available):

.. code-block:: bash

    python -m venv trucks_env

Activate the virtual environment:

.. tabs::

   .. tab:: Linux or Mac

        .. code-block:: bash

            source trucks_env/bin/activate

   .. tab:: Windows

    For bash terminals:

      .. code-block:: bash

            source trucks_env/Scripts/activate

    Or, in anaconda prompt / command prompt terminals:

      .. code-block:: bash

            trucks_env/Scripts/activate

Change directory inside the repo:

.. code-block:: bash

    cd ../<repo name>/

And install the required packages:

.. code-block:: bash

    python -m pip install . -r requirements.txt

If you are struggling to install some package on Windows, such as rasterio, you
may need to manually download the required binary files as `described here
<https://iotespresso.com/installing-rasterio-in-windows/#:~:text=%20Installing%20rasterio%20in%20Windows%20%201%20Step,should%20be%20installed.%20%20...%20This...%20More%20>`_
and update the package accordingly in the `requirements.txt`, based on the binaries available
at the that time.

For example, if the only binary available is for `rasterio==1.2.10`,
then you still can not install `rasterio=1.2.1` as given in the requirements file.
You instead need to update the version in the `requirements.txt`. We cannot
guarantee this version is compatible with this project's code however, which is why
a Conda environment is the recommended route.
