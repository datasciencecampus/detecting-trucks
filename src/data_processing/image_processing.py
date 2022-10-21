"""
Colletion of functions that handle preprocessing and chipping of images.
"""
# Standard library
from pathlib import Path
from typing import List

# Third party
import geopandas as gpd
import numpy as np
import rasterio as rio
from osgeo import gdal
from rasterio.mask import mask
from rasterio.transform import from_bounds
from shapely.geometry import box
from tqdm import tqdm

# Project
from utils.file_handling import generate_file_list

from .masking import cloud_mask, get_roads


def add_nodata_layer(location: str, raw_img_dir: Path, img_dir: Path):
    """
    Add a 'nodata' layer to rasters with gdal.

    Parameters
    ----------
    location : str
        Location descriptive name - used in naming files.
    raw_img_dir : pathlib.Path
        Path to the directory raw S2 images exported from GEE are stored. The
        default relative path is '../data/<location>/raw/s2_images'.
    img_dir : pathlib.Path, optional
        Path to the directory where processed S2 images are to be saved.

    Returns
    -------
    Creates modified image files and saves to img_dir path.

    """
    raw_image_list = generate_file_list(raw_img_dir, "tif", location)
    for image in raw_image_list:
        gdal.BuildVRT(str(img_dir.joinpath("tif.vrt")), [str(image)], VRTNodata=-999)
        gdal.Translate(
            str(img_dir.joinpath(image.stem + "_temp.tif")),
            str(img_dir.joinpath("tif.vrt")),
            a_nodata=-999,
            options=gdal.TranslateOptions(
                format="GTiff", creationOptions=["COMPRESS=LZW"]
            ),
        )

    processed_image_list = generate_file_list(img_dir, "tif", [location, "_temp"])
    for image in processed_image_list:
        image.replace(image.parent.joinpath(image.stem[:-5] + image.suffix))


def create_road_buffer_shp_file(img_file: Path, location: str, data_dir: Path):
    """
    Read in S2 image file, extract road data and create shapefile with buffer.

    This involves:
        1. Read image and extract location data.
        2. Acquire the road network data from OpenStreetMap (OSM) using OSMNX,
           for given position.
        3. Create buffer.
        4. Save shapefile of buffered road data.

    Parameters
    ----------
    img_file : pathlib.Path or str
        The image file to be processed.
    location : str
       The string representing physical location, as used in filenames.
    data_dir : pathlib.Path
        The path to the directory where shapefile to be saved.

    Returns
    -------
    Shapefile created in place.

    """
    with rio.open(img_file) as file:
        use_crs = file.crs.to_string()
        road_buffer_gdf = get_roads(
            img=file, projected_crs=use_crs, buffer_distance=15, network_type="drive"
        )
        road_buffer_gdf.to_crs(use_crs, inplace=True)
        img_box = box(*file.bounds)
        img_box = gpd.GeoDataFrame(geometry=[img_box], crs=use_crs)
        road_buffer_gdf = gpd.clip(road_buffer_gdf, img_box)

    road_buffer_gdf.to_file(data_dir.joinpath(f"road_buffer_{location}.shp"))


def generate_grid_shp(
    raster_file: Path,
    road_buffershp_fp: Path,
    output_path: Path,
    output_file: str,
    dimensions_metres: int,
    interval_metres: int,
    clip_grid_to_img: bool = True,
):
    """
    Generate a grid shapefile.

    Generates a shapefile of grids of specified size and overlap, where the road
    buffer geometry intersects.

    Parameters
    ----------
    raster_file : pathlib.Path or str
        Filepath of image file to grid.
    road_buffershp_fp : pathlib.Path or str
        Filepath to road buffer shapefile.
    output_path : pathlib.Path
        Filepath to directory shapefile to be saved in.
    output_file : str
        Desired name for output file (including extension).
    dimensions_metres : int
         Size of desired grid in both x and y dimensions, in unit of metres.
    interval_metres : int
        Size of interval between grids for overlap, in unit of metres.
    clip_grid_to_img : bool, optional
        If True, grid is clipped to true extent of the image. The default is True.

    Returns
    -------
    The shapefile is written to file.

    """
    with rio.open(raster_file) as img:
        xmin, ymin, xmax, ymax = img.bounds
        crs = img.crs.to_string()
    xgrids = list(range(int(np.floor(xmin)), int(np.ceil(xmax)), interval_metres))
    ygrids = list(range(int(np.floor(ymin)), int(np.ceil(ymax)), interval_metres))
    xgrids = [x for x in xgrids if x < xmax]
    ygrids = [y for y in ygrids if y < ymax]
    grids, ids = [], []
    for x in xgrids:
        for y in ygrids:
            grids.append(box(x, y, x + dimensions_metres, y + dimensions_metres))
            x_text = int(xgrids.index(x) * dimensions_metres / 10)
            y_text = int(ygrids.index(y) * dimensions_metres / 10)
            ids.append(f"{x_text}_{y_text}")
    gdf = gpd.GeoDataFrame({"location": ids, "geometry": grids}, crs=crs)
    roads = gpd.read_file(road_buffershp_fp)
    if roads.crs.to_string() != crs:
        roads = roads.to_crs(crs)
    gdf = gdf[gdf.intersects(roads.unary_union)]
    if clip_grid_to_img:
        gdf = gpd.clip(
            gdf, gpd.GeoDataFrame(geometry=[box(xmin, ymin, xmax, ymax)], crs=crs)
        )
    gdf["area"] = gdf["geometry"].area
    output_filepath = output_path.joinpath(output_file)
    gdf.to_file(output_filepath)
    print(f"Exported grids shapefile to {output_filepath}.")


def create_chips_from_grid(raster_file: Path, grid_shp_fp: Path, chip_output_fp: Path):
    """
    Create chip image files from input raster/image file and grid shapefile.

    Parameters
    ----------
    raster_file : pathlib.Path, str
        Directory and name of raster to be chipped.
    grid_shp_fp : pathlib.Path, str
        Directory and name of grid shapefile.
    chip_output_fp : pathlib.Path, str
        Directory where chip images to be saved.

    Returns
    -------
    New image files generated in place.

    """
    gdf = gpd.read_file(grid_shp_fp)
    to_do = len(gdf)
    print(f"There are {to_do} chips to create.")
    for i, row in tqdm(gdf.iterrows(), total=gdf.shape[0]):
        id_val = row["location"]
        with rio.open(raster_file) as file:
            out_img, out_transform = mask(
                file, shapes=[row["geometry"]], crop=True, nodata=-999
            )
            prof = file.meta
        out_fp = f"{chip_output_fp}{id_val}.tif"
        prof.update(
            width=out_img.shape[2],
            height=out_img.shape[1],
            transform=out_transform,
            compress="lzw",
        )
        with rio.open(out_fp, "w", **prof) as file:
            file.descriptions = tuple(["Blue", "Green", "Red", "Cloud", "Cloud Shadow"])
            file.write(out_img)


def create_temporal_chips_from_grid(
    img_file_list: List[Path],
    chips_temporal_dir: Path,
    grid_shp_fp: Path,
    output_partial_filename: str,
):
    """
    Create chipped temporal mean composite image files.

    For each chip geometry in the grid shapefile, all images across the date
    range extracted get stacked. The mean pixel value of each pixel, across all
    these observations (i.e. the temporal mean), is calculated and returned.
    New chipped images with the temporal mean pixel values are generated.

    Parameters
    ----------
    img_file_list : list(pathlib.Path)
        List of filepaths for each image file to be composited.
    chips_temporal_dir : pathlib.Path
        Path to the directory where chipped temporal composite images (to be)
        stored.
    grid_shp_fp : pathlib.Path
        File path to grid shapefile.
    output_partial_filename : str
        Partial filename for output file (will be appended with grid info).

    Returns
    -------
    Image chips with per pixel temporal mean values created in place.

    """
    chip_output_fp = chips_temporal_dir.joinpath(output_partial_filename)
    gdf = gpd.read_file(grid_shp_fp)
    try:
        existing_imgs = generate_file_list(chips_temporal_dir, "tif", ["_mean_"])
        if existing_imgs:
            # If chipped images present (for example from partially complete run)
            # ignore those rows in the shapefile to avoid unnecessary re-chipping
            existing_chips_list = [fp.stem.split("mean_")[1] for fp in existing_imgs]
            gdf = gdf[~gdf.location.isin(existing_chips_list)]
    except FileNotFoundError:
        pass
    to_do = len(gdf)
    print(f"There are {to_do} chips still to be processed:")
    for i, row in tqdm(gdf.iterrows(), total=gdf.shape[0]):
        id_val = row["location"]
        temporal_list = []
        with rio.open(img_file_list[0]) as img_file:
            prof = img_file.meta
        for img in img_file_list:
            with rio.open(img) as img_file:
                img_arr, out_transform = mask(
                    img_file, shapes=[row["geometry"]], crop=True, nodata=-999
                )
            img_arr = np.ma.array(img_arr, mask=img_arr == -999)
            img_arr = cloud_mask(img_arr, threshold=20)

            if img_arr.max() == -999.0:
                continue
            else:
                temporal_list.append(img_arr)
        temporal_list = np.ma.stack(temporal_list, axis=0)
        mean_arr = temporal_list.mean(axis=0).astype("float32")
        mean_arr = mean_arr.filled(-999.0)

        out_fp = f"{chip_output_fp}{id_val}.tif"
        xmin, ymin, xmax, ymax = row.geometry.bounds
        prof.update(
            width=mean_arr.shape[2],
            height=mean_arr.shape[1],
            transform=from_bounds(
                xmin, ymin, xmax, ymax, mean_arr.shape[2], mean_arr.shape[1]
            ),
            compress="lzw",
        )
        with rio.open(out_fp, "w", **prof) as file:
            file.descriptions = tuple(["Blue", "Green", "Red", "Cloud", "Cloud Shadow"])
            file.write(mean_arr)
