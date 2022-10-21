"""
Collection of functions for handling road networks in image processing and
masking clouds in image processing.
"""

import geopandas as gpd
import numpy as np
import osmnx
import pandas as pd
import rasterio
from shapely.geometry import box
from skimage.filters.rank import maximum, minimum
from skimage.morphology import square


def check_highway_type(
    network: gpd.GeoDataFrame, acceptable_highways: list = ["motorway", "trunk"]
) -> gpd.GeoDataFrame:
    """
    Extract highways of specified types only.

    By default, this extracts only high importance roads.

    Parameters
    ----------
    network : gpd.GeoDataFrame
        GeoDataFrame of road network.
    acceptable_highways : list, optional
        List of the OpenStreetMaphighway types to be extracted.
        (See: https://wiki.openstreetmap.org/wiki/Key:highway). The default is
        ["motorway", "trunk"], i.e. high importance roads only.

    Returns
    -------
    geopandas.GeoDataFrame
        Filtered network including only given road types.
    """
    highway_links = [highway + "_link" for highway in acceptable_highways]
    acceptable_highways = acceptable_highways + highway_links

    network_highway = pd.DataFrame(columns=network.columns)

    for highway in acceptable_highways:
        highway_df = network[
            network["highway"].apply(lambda x: highway == x or highway in x)
        ]
        network_highway = pd.concat([network_highway, highway_df])

    return network_highway


def get_roads(
    img: rasterio.io.DatasetReader,
    projected_crs: str,
    buffer_distance: int,
    network_type: str = "drive",
) -> gpd.GeoDataFrame:
    """
    Extract road network from image.

    Queries OpenStreetMap using OSMnx and the bbox of an image and outputs a
    GeoDataFrame. The GeoDataFrame is then buffered in a projected coordinate
    system to confidently capture roads.

    Parameters
    ----------
    img : rasterio.io.DatasetReader
        Rasterio DatasetReader of image
    projected_crs : str
        The EPSG code for the projected CRS.
    buffer_distance : int
        Distance in which to buffer road network (in pixels[?])
    network_type : str, optional
        Type of street network to query, the default value is "drive".

    Returns
    -------
    gpd.GeoDataFrame
         Buffered multipolygon of an image's road network

    """
    if img.crs.to_string() != "EPSG:4326":
        minx, miny, maxx, maxy = img.bounds
        g = box(minx, miny, maxx, maxy)
        temp_gdf = gpd.GeoDataFrame(geometry=[g], crs=img.crs.to_string())
        temp_gdf = temp_gdf.to_crs("EPSG:4326")
        minx, miny, maxx, maxy = temp_gdf["geometry"][0].bounds

    else:
        minx, miny, maxx, maxy = img.bounds

    # north south east west order
    network = osmnx.graph.graph_from_bbox(maxy, miny, minx, maxx)
    nodes, roads = osmnx.graph_to_gdfs(network, network_type)

    crs = roads.crs

    highways = check_highway_type(roads)
    highways_gdf = gpd.GeoDataFrame(
        highways, crs=roads.crs, geometry=highways["geometry"]
    )

    highways_gdf.to_crs(projected_crs, inplace=True)
    highways_union = highways_gdf.unary_union.buffer(buffer_distance)

    highways_gdf = gpd.GeoDataFrame(crs=highways_gdf.crs, geometry=[highways_union])
    highways_gdf.to_crs(crs, inplace=True)

    return highways_gdf


def cloud_mask(
    img: np.ndarray,
    threshold: int = 25,
    expand_edge: int = 100,
    mask_shadow: bool = True,
):
    """
    Masks pixels with cloud probability above given threshold.

    Parameters
    ----------
    img : np.ndarray
        Array representation of raster to be processed.
    threshold : int, optional
        The cloud probability threshold above which pixels are masked. The
        default value is 25 (i.e. 25% probability).
    expand_edge : int, optional
        Number of pixels by which to create a box around cloud to mask out
        edge of clouds also. (Refraction on cloud edges can be easily confused
        with truck colour signal). The default value is 100.
    mask_shadow : bool, optional
        Decides whether to also mask the shadow caused by clouds. The default
        behaviour is True.

    Returns
    -------
    np.ma.array
        Array representation of processed image with pixels of cloud probability
        over the assigned threshold masked out (and those nearby as controlled
        by expand_edge).

    """
    initial_mask = img.mask
    cloud = img[3].astype("uint8")
    cloud = np.where(cloud > threshold, 1, 0)
    if mask_shadow:
        shadow = img[4].astype("uint8")
        cloud = np.maximum(cloud, shadow)
    cloud = minimum(cloud, square(3), mask=~img[3].mask)
    cloud = maximum(cloud, square(expand_edge), mask=~img[3].mask)
    cloud = np.broadcast_to(cloud == 1, img.shape)
    img = np.ma.masked_where(np.logical_or(cloud, initial_mask), img)
    return img
