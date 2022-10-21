# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:light
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.13.8
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# + tags=["active-py"]
"""
Notebook for executing the data extraction process.

This is supplied as a .py file but is designed to be converted to a jupyter
notebook using jupytext, which can be achieved by executing 'create_notebook.py'.

Once built, the notebook contains extensive, step-by-step, instructions on how
to acquire the required Sentinel-2 imagery data.
"""
# -

# # Prepare processed satellite images
#
# This notebook is intended to guide the user in how to extract the [Copernicus Sentinel-2](https://sentinel.esa.int/web/sentinel/missions/sentinel-2) images from [Google Earth Engine (GEE)](https://earthengine.google.com/) and process them into the required format for further analysis.
#
# This includes the following steps:
#
# 1. ##### [Set-up Google Earth Engine (GEE)](#GEE_setup)
# 1. ##### [Select Road(s) of Interest](#select_roads)
#     - ###### [Extract OpenStreetMap (OSM) file](#extract_OSM)
#     - ###### [Extract roads data from OSM file and export as shapefile.](#export_roads_shape)
# 1. ##### [Process shapefile and upload to your GEE account](#upload_to_GEE)
# 1. ##### [Export Sentinel-2 images from GEE](#export_tif)
# 1. ##### [Appendix](#appendix)

# ## Set-up & initialize Google Earth Engine (GEE)<a class="anchor" id="GEE_setup"></a>
#
# In order to use the Earth Engine (`ee`) python package, a GEE account is necessary.
#
# If you do not already have one, you will need to [sign-up for an account](https://earthengine.google.com/signup/).
#
# You will also need to authenticate your sign-in by running >> `earthengine authenticate` in your terminal. This will redirect you to a website and generate a secure authorization token.

# + tags=["active-ipynb"]
# # third party packages
# import ee
# import geopandas as gpd
#
# # project packages
# from data_processing.extract_gee_images import (
#     dissolve_and_buffer_roads,
#     export_s2_collection,
#     get_roads_geometries,
#     image_datetime_df,
# )
# from utils.file_handling import set_up_data_structure
#
# # initialise GEE
# ee.Initialize()
# -

# # Select Road(s) of Interest<a class="anchor" id="select_roads"></a>
#
# This project will develop a model that can detect the presence of trucks within satellite imagery. The first step is to define the section of road(s) you are interested in detecting trucks on. The next few steps will guide you how to select an area of interest. The key roads within this area will then be extracted and satellite imagery for these roads will be acquired.
#
# **Note:** in order to avoid unnecessary processing and storage, the satellite images are only extracted along the geometry and extent of the roads.
#
# ## Extract OpenStreetMap (OSM) file<a class="anchor" id="extract_OSM"></a>
#
# The first step is to define our area of interest. We do this by selecting a polygon covering our desired area using the OSM [BBBikes extract tool](https://extract.bbbike.org/) and download a custom OSM file.
#
# 1. Follow the link and use the map to define your area of interest for open street map roads extraction.
# 1. Ensure the Format is set to __Proctocolbuffer (PBF)__.
# 1. Name your new location.
# 1. Enter your email address and hit "extract"
# <img src="imgs/extract_osm_tool.png" alt="screenshot of the required fields in the BBBike tool" width="350"/>
# 1. After a few minutes, the osm.pbf file will be sent to your specified email address.
# 1. Move this file to the top-level `data` directory in this repository (this will be relocated shortly).
# 1. __Rename the file:__ This naming convention will be retained throughout the entire process so use a meaningful name that corresponds to the area of interest. It is recommended you use snake case (e.g. "south_east_england.osm.pbf" or "greater_berlin.osm.pbf"). Note: The default name of the file generated is likely in the format of `planet_-1.454,52.02_-1.214,52.114.osm`, which will present problems further downstream in how GEE interprets filepaths so this _must_ be changed.
#
# _Note: you can also download files directly for preset locations using the `pyrosms` package: see [Pyrosm basic usage](https://pyrosm.readthedocs.io/en/latest/basics.html)._

# Now, set the location variable by entering the name of the location you selected. This should match the name of the `.osm.pbf` file (without the file extensions or full path):
#

# + tags=["active-ipynb"]
# # set the location variable, ensuring this matches the name in the .osm.pbf file you exported (without extensions or full path)
# location = input("location:")
# -

# Run the following to set up the data directory structure (this will also move your file into a "raw" unmutable subdirectory).

# + tags=["active-ipynb"]
# filepath, loc_data_dir = set_up_data_structure(location)
# -

# ## Extract roads data from OSM file and export as shapefile<a class="anchor" id="export_roads_shape"></a>
#
# The following step checks the area of interest for the presence of roads, as defined in the OSM. By default, it extracts main roads only (controlled by the `export_types` arg below). This is because the truck detection procedure works best of major roads and highways.
#
#
# **Note:** Here we are using using the extracted osm.pbf file, but it is also possible to replace fp with a bounding box of our area of interest.
#
# **Note:** If your chosen area does not contain any OSM roads, you will receive the following error message:<br>
# `AttributeError: 'NoneType' object has no attribute 'is_empty'`

# + tags=["active-ipynb"]
# get_roads_geometries(
#     str(filepath), location, loc_data_dir, export_types=("motorway", "trunk")
# )
# -

# ## Process shapefile and upload to your GEE account <a class="anchor" id="upload_to_GEE"></a>
#

# + tags=["active-ipynb"]
# # Read in shapefile as a geopandas object
# road_centre_lines = gpd.read_file(loc_data_dir.joinpath(f"{location}_roads.shp"))
# road_centre_lines
# -

# ### Check Coordinate Reference System (CRS)
#
# We need to check the most appropriate CRS is being used for our location.

# + tags=["active-ipynb"]
# road_centre_lines.crs
# -

# Check the CRS for the given shapefile in the output for cell above.
#
# This should not be in a _geographic CRS_ (such as WGS 84). If it is, you will need to convert to this to a _projected CRS_ using the cell below.
#
# For example if your selected location is in the UK, the shapefile may currently have the geographic CRS **EPSG:4326**, which you will need to reproject to a projected CRS for the UK, such as **EPSG:27700**.
#
# To find the most suitable projected CRS for your given location, use the [**epsg.io**](http://epsg.io/) browser and enter your location to find the EPSG number.

# + tags=["active-ipynb"]
# crs = input("Enter CRS in the following format: EPSG:<number> ")
# road_centre_lines = road_centre_lines.to_crs(crs=crs)
# road_centre_lines.crs
# -

# Next we dissolve the data, add a buffer and save the output file:

# + tags=["active-ipynb"]
# dissolve_and_buffer_roads(location, loc_data_dir, road_centre_lines)

# + tags=["active-ipynb"]
# with open(loc_data_dir.joinpath(f"{location}_buffered_roads_upload.prj")) as prj_file:
#     projection_file_text = prj_file.read()

# if "TOWGS84" not in projection_file_text:
#     print(
#         "Warning! The TOWGS84 parameter was note detected in the '.prj' file associated with the geometry."
#         " Please see instructions below for advice."
#     )
# else:
#     print(
#         "TOWGS84 parameter detected in the output files. You can probably ignore the text below."
#     )
# -

# **NOTE:** Check the output of the cell above. If a warning was generated this section is probably relevant for you. If the TOWGS84 paramteter _was_ detected, you can probably ignore what follows and upload to GEE.
#
# It may be important to check the `<location>_buffered_roads_upload.prj` file, depending on the CRS projection you have selected. If using a [UTM CRS projection](https://en.wikipedia.org/wiki/Universal_Transverse_Mercator_coordinate_system), the following may not be necessary, however, if you have chosen a a country specific CRS it is likely you will need to.
#
# The `<location>_buffered_roads_upload.prj` file, (which is part of the shapefile generated above), describes the the coordinate system and projection information. However, this file can often omit some essential parameters that GEE uses for correctly positioning the roads for the image extraction, namely the `TOWGS84 parameter` as outlined [here](https://groups.google.com/g/google-earth-engine-developers/c/QpnqHeu8Bz4/m/-Cw6SE7RAAAJ). If this parameter is not present in your `.prj` file you may need to manually modify this, otherwise your images will likely be offset from the true road positions.
#
# A more detailed parameter list (inclusive of the above parameter) is available through the [**epsg.io**](http://epsg.io/) browser. On the page for your chosen CRS system (e.g. EPSG27700) you should scroll down the page, copy the text in the WTK format box (example below) and paste this into the `<location>_buffered_roads_upload.prj` file (overwriting what is there). This is the version you should upload in the next step.
# <img src="imgs/epsg_wtk_example.png" alt="screenshot of the WTK text field from epsg.io" width="800"/>

# ### Upload final shapefile to your GEE account as an asset
#
# The latest version of the shapefiles (`<location>_buffered_roads_upload.shp` and its accompanying files) now need to be uploaded to [GEE](https://code.earthengine.google.com/) as an asset (see [here for instructions](https://developers.google.com/earth-engine/guides/table_upload)).
#
# _Note:_ you will need to have [set up a free Google Earth Engine account](https://earthengine.google.com/new_signup/) to upload the custom shapefile.
#
# _Note:_ you can check the progress of your upload under the "tasks" tab on GEE or by running `ee.batch.Task.list()` in this notebook.
#
# Once the asset upload is *complete*, move on to the next step.

# ## Export Sentinel-2 images from GEE<a class="anchor" id="export_tif"></a>
#
# The following cells will trigger GEE to extract the S2 images of your area of interest, between the dates defined below.
#
# By default, these images are then saved into the Google Drive of the Google account associated with your GEE account.
#
# _**Note:** By default images are exported to Google Drive. It is possible to automatically download images to your local machine instead (by setting `google_drive=False` below). However, this is not recommended because GEE restricts the image size for direct retrieval. These size restrictions are not imposed when saving to the cloud._
#

# + tags=["active-ipynb"]
# # set range of dates for GEE image extraction
# start_date = "2021-05-01"
# end_date = "2021-09-20"
# -

# **NOTE:** you will need to copy the path from the asset location in [GEE](https://code.earthengine.google.com/) and enter this below. The quickest way to get this to click on your data asset table in GEE and then copy from `Table ID`.
#
# Depending on how you uploaded the files, this will likely be in the format of either:
# 1) `projects/earthengine-legacy/assets/users/<username>/<asset_name>`, or,
#
# 2) `projects/<project_name>/assets/<asset_name>`.
#
#
#
# **PLEASE NOTE:** Depending on the size of the area of interest being extracted and the number of observations available within the date range provided, the image extraction on GEE _can_ take hours to complete. The code below will not take as long to execute, but GEE will likely take a while in the background to complete it's tasks. After the cell below has finished executing, closing this notebook will not affect your image extraction.

# + tags=["active-ipynb"]
# gee_asset_path = input("Enter path to GEE asset:")
# feature = ee.FeatureCollection(gee_asset_path)
# export_s2_collection(
#     prefix_out=location,
#     crs=crs,
#     geometry=feature,
#     start=start_date,
#     end=end_date,
#     data_dir=loc_data_dir,
#     mask=True,
#     google_drive=True,
#     folder_name=f"S2_{location}_road_imagery",
# )
# -

# You can monitor GEE's progress with the task manager in GEE itself, e.g.
# <img src="imgs/gee_task_manager.png" alt="screenshot of the GEE task manager" width="350"/>
# Or, by periodically executing the cell below:

# + tags=["active-ipynb"]
# # Periodically run this to see how GEE is progressing with your request
# ee.batch.Task.list()
# -

# ## Download image files from Drive to local raw data directory
# By default, GEE will have exported the S2 satellite images to the associated Google Drive (with the folder name defined above, or the default "S2_road_images").
#
# These now need to be downloaded and the TIF images relocated to the `s2_images` subdirectory in the `raw` subdirectory within the location specific data directory (i.e. `data/<location_name>/raw/s2_images`).

# ## Your images are now ready for further processing and model implementation.
#
# Return to the tutorial documentation to continue the walkthrough.

# -----
# ## Appendix: <a class="anchor" id="appendix"></a>
# ### Check the details of Sentinel 2 images at area of interest
# Below, you can check for the existence of S2 imagery at a specified area of interest within a given date range.
#
# This will return a dataframe contains metadata on cloud percentage, date and time of observation, image ID and which satellite (A or B).
#
# Enter the latitude and longitude for your area of interest in `xy` below:

# + tags=["active-ipynb"]
# xy = (34.775703, 0.590238)
# image_datetime_df(xy, start=start_date, end=end_date)[1:60]
