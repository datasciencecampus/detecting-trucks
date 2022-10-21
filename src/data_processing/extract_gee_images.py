"""
Script of functions for extracting Sentinel-2 images from Google Earth Engine (GEE).

This is intended to be used in conjunction with the "extract_satellite_imagery" notebook.
"""

# standard library
import zipfile
from pathlib import Path

# third party
import ee
import geopandas as gpd
import pandas as pd
import pyrosm
import requests

# project
from utils.file_handling import set_data_dir


def get_roads_geometries(
    osm_filepath: str,
    location: str,
    data_dir: Path,
    export_types: tuple = ("motorway", "trunk"),
):
    """
    Convert osm.pdf file to shapefile of road data.

    Take an OpenStreetMap (OSM) file and extract roads data from it. Then,
    create and export a shapefile of road data.

    NOTE: pyrosm.OSM can also take a bounding box as the osm_filepath argument

    Parameters
    ----------
    osm_filepath : str
        Path to OSM proctocolbuffer (osm.pbf) datafile in string format.
    location : str
        Descriptive name for area of interest, as used in the file names.
    data_dir : pathlib.Path
        Path to the data directory.
    export_types : tuple(str), optional
        The type of roads to extract under the 'OSM highway tag' classification
        system. The default is ['motorway', 'trunk'], i.e. high importance roads
        only. See: https://wiki.openstreetmap.org/wiki/Key:highway .

    Returns
    -------
    New shapefile data file created in place.

    """
    osm = pyrosm.OSM(osm_filepath)
    roads = osm.get_network(network_type="driving")
    roads = roads[~roads.is_empty]
    roads = roads.dissolve(by="highway", as_index=False)
    roads = roads.to_crs("EPSG:4326")

    roads_export = roads[roads["highway"].isin(export_types)]
    if roads_export.shape[0] > 0:
        roads_export.to_file(data_dir.joinpath(f"{location}_roads.shp"))
        print(f"Exported {osm_filepath}")


def dissolve_and_buffer_roads(
    location: str, loc_data_dir: Path, road_centre_lines: gpd.GeoDataFrame
):
    """
    Dissolve along roads, add buffer and output modified shapefile.

    Parameters
    ----------
    location : str
        Descriptive name for area of interest, as used in the file names.
    loc_data_dir : pathlib.Path
        Path to the data/<location> subdir.
    road_centre_lines : geopandas.GeoDataFrame
        The geodataframe of the roads shapefile with corrected CRS.

    Returns
    -------
    Modified shapefile saved in place.

    """
    # dissolve roads
    road_centre_lines["diss"] = 1
    road_centre_lines = road_centre_lines.dissolve("diss", as_index=False)

    # add buffer
    road_centre_lines["geometry"] = road_centre_lines["geometry"].buffer(15)

    # save to new shapefile
    road_centre_lines.to_file(
        loc_data_dir.joinpath(f"{location}_buffered_roads_upload.shp")
    )


def get_image_info(img):
    """Define a dictionary of data to extract from image and pass to ee.Feature()."""
    row_val = {
        "img_id": img.get("system:index"),
        "date_time": img.date().format("yyyy-MM-dd HH:MM:SS"),
        "cloudpercent": img.get("CLOUDY_PIXEL_PERCENTAGE"),
        "satellite": img.get("SPACECRAFT_NAME"),
    }
    return ee.Feature(None, row_val)


def image_datetime_df(
    xy_coords: tuple,
    start: str = "2019-01-01",
    end: str = "2020-10-31",
    max_cloud_percent: int = 15,
) -> gpd.GeoDataFrame:
    """
    Check for existence of Sentinel 2 images and return details.

    Generate a dataframe of S2 images at a given point, within a given date range.
    The dataframe contains metadata on cloud percentage, date and time of observation,
    image ID and which satellite (A or B).

    Parameters
    ----------
    xy_coords : tuple
        Tuple of (long, lat) for location of interest.
    start : str, optional
        Starting date for requested time period (in format yyyy-MM-dd).
        The default is "2019-01-01".
    end : str, optional
        Ending date for requested time period (in format yyyy-MM-dd).
        The default is "2020-10-31".
    max_cloud_percent : int, optional
        Threshold for maximum cloud percentage. If image has cloud coverage in
        excess of this cloud percent, it will be omitted. The default is 15.

    Returns
    -------
    geopandas.GeoDataFrame
        Dataframe of metadata on cloud percentage, date and time of observation,
        image ID and which satellite (A or B).

    """
    use_pt = ee.Geometry.Point(xy_coords)
    s2c = (
        ee.ImageCollection("COPERNICUS/S2_SR")
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", max_cloud_percent))
        .filterBounds(use_pt)
        .filterDate(start, end)
        .sort("system:time_start")
    )

    feature_coll = ee.FeatureCollection(s2c.map(get_image_info))
    property_list = [i["properties"] for i in feature_coll.getInfo()["features"]]

    return pd.DataFrame(property_list)


def add_shadow_bands(img):
    """
    Add dark pixels, cloud projection, and identified shadows as bands to image.

    This function has been adapted from the GEE documentation:
    https://developers.google.com/earth-engine/tutorials/community/sentinel-2-s2cloudless

    Parameters
    ----------
    img : ee.ImageCollection
        The image to be processed.

    Returns
    -------
    ee.ImageCollection
        Image with additional bands included.

    """
    # Identify water pixels from the SCL band.
    not_water = img.select("SCL").neq(6)

    # Identify dark NIR pixels that are not water (potential cloud shadow pixels).
    nir_drk_thresh = 0.15

    cld_prj_dist = 1

    sr_band_scale = 1e4
    dark_pixels = (
        img.select("B8")
        .lt(nir_drk_thresh * sr_band_scale)
        .multiply(not_water)
        .rename("dark_pixels")
    )

    # Determine the direction to project cloud shadow from clouds ..
    # .. (assumes UTM projection).
    shadow_azimuth = ee.Number(90).subtract(
        ee.Number(img.get("MEAN_SOLAR_AZIMUTH_ANGLE"))
    )

    img = img.addBands(img.select("probability").gt(25).rename("clouds"))

    # Project shadows from clouds for the distance specified by the cld_prj_dist input.
    cld_proj = (
        img.select("clouds")
        .directionalDistanceTransform(shadow_azimuth, cld_prj_dist * 10)
        .reproject(**{"crs": img.select(0).projection(), "scale": 100})
        .select("distance")
        .mask()
        .rename("cloud_transform")
    )

    # Identify the intersection of dark pixels with cloud shadow projection.
    shadows = cld_proj.multiply(dark_pixels).rename("shadows")

    return img.addBands(shadows)


def get_img_dates(img, tmp_list):
    """Extract observation date from image."""
    return ee.List(tmp_list).add(img.date().format("yyyy-MM-dd"))


def export_s2_collection(
    prefix_out,
    crs,
    geometry,
    start,
    end,
    data_dir,
    mask=False,
    google_drive=True,
    folder_name="fei_road_s2",
):
    """
    Export S2 imagery for given location and dates with GEE.

    Using the geometric data from a shapefile, S2 images in the B2, B3
    and B4 bands are exported from GEE for the given location and between the
    specified dates. Images saved in TIF format.

    Note: By default images are exported to Google Drive. It is possible to
    automatically download images to local instead (by setting google_drive=False).
    However, this is not recommended because GEE restricts the image size for
    direct retrieval. These size restrictions are not imposed when saving to the
    cloud.

    Parameters
    ----------
    prefix_out : str
        Location descriptive name - used in naming files.
    crs : str
        The CRS. Which should be a projected CRS and match that of the shapefile.
    geometry : obj (ee.featurecollection.FeatureCollection)
        Feature collection of the shapefile.
    start : str
        Starting date for requested time period (in format yyyy-MM-dd).
    end : str
        Ending date for requested time period (in format yyyy-MM-dd).
    data_dir : pathlib.Path
        Path to the data directory.
    mask : bool, optional
        If True, image clipped to FeatureCollection; meaning data not covered
        by the geometry of at least one feature from the collection is masked.
        The default is False.
    google_drive : bool, optional
        If True, exported S2 images are saved to Google Drive. If False, exported
        images saved to local disk. The default is True.
    folder_name : str, optional
        Name of folder if saved in Google Drive. The default is "fei_road_s2".

    Returns
    -------
    TIF images are exported and saved to specified location.

    """
    img_dir = set_data_dir(data_dir, "raw")

    s2cfull = (
        ee.ImageCollection("COPERNICUS/S2_SR")
        .filterBounds(geometry)
        .filterDate(start, end)
    )
    s2ccloud = (
        ee.ImageCollection("COPERNICUS/S2_SR")
        .filter(ee.Filter.gt("CLOUDY_PIXEL_PERCENTAGE", 50))
        .filterBounds(geometry)
        .filterDate(start, end)
    )
    s2_cloud_prob = (
        ee.ImageCollection("COPERNICUS/S2_CLOUD_PROBABILITY")
        .filterBounds(geometry)
        .filterDate(start, end)
    )

    # join the cloud prob to the images by ID
    inner_join = ee.Join.inner()
    filter_id = ee.Filter.equals(leftField="system:index", rightField="system:index")

    joined_cloud_img = inner_join.apply(s2cfull, s2_cloud_prob, filter_id)

    s2cuse = ee.ImageCollection(
        joined_cloud_img.map(
            lambda f: ee.Image.cat(f.get("primary"), f.get("secondary"))
        )
    )

    s2cuse = s2cuse.map(add_shadow_bands)

    tmp_list = ee.List([])
    # Doing it this way round as want all images mosaiced in AOI to have ..
    # .. cloud coverage < specified overall cloud cover percent
    set_of_img_dates = set(s2cfull.iterate(get_img_dates, tmp_list).getInfo()) - set(
        s2ccloud.iterate(get_img_dates, tmp_list).getInfo()
    )
    print(set_of_img_dates)
    for img_date in set_of_img_dates:
        endd = ee.Date(img_date).advance(1, "day").format("yyyy-MM-dd").getInfo()
        outimg = (
            s2cuse.filterDate(img_date, endd)
            .select(["B2", "B3", "B4"])
            .mosaic()
            .divide(10000)
            .addBands(
                s2cuse.filterDate(img_date, endd).select(["probability"]).mosaic()
            )
            .addBands(s2cuse.filterDate(img_date, endd).select(["shadows"]).mosaic())
        )

        if mask:
            outimg = outimg.clipToCollection(geometry)
        if google_drive:
            task = ee.batch.Export.image.toDrive(
                image=outimg.float().unmask(-999),
                folder=folder_name,
                description=f"s2a_{prefix_out}_{img_date}",
                region=geometry.geometry(),
                maxPixels=1e13,
                crs=crs,
                scale=10,
            )
            task.start()
        else:
            url = (
                outimg.float()
                .unmask(-999)
                .getDownloadURL(
                    {
                        "name": f"s2a_{prefix_out}_{img_date}",
                        "region": geometry.geometry(),
                        "scale": 10,
                        "crs": crs,
                        "filePerBand": False,
                    }
                )
            )
            req = requests.get(url, stream=True)
            with open(data_dir.joinpath("temp_img.zip"), "wb") as file:
                for chunk in req.iter_content(chunk_size=1024):
                    file.write(chunk)
            z = zipfile.ZipFile(data_dir.joinpath("temp_img.zip"))
            z.extractall(img_dir)
            print(
                f"Exported image to {str(img_dir.joinpath(f's2a_{prefix_out}_{img_date}.tif'))}"
            )
