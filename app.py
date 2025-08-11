import os
from datetime import datetime
import re # For splitting vendor codes
import threading # For opening browser without blocking
import webbrowser # For opening browser
import time # For delay before opening browser
import random # For population heatmap point generation
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point, Polygon
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import json
import hashlib
import math
from functools import lru_cache
from mini import fetch_question_data
from scipy import stats  # NEW: Added for improved statistical functions

# Configuration settings are centralized in ``config.py`` so that credentials
# and other tunable constants live in a single location.
from config import (
    METABASE_URL,
    METABASE_USERNAME,
    METABASE_PASSWORD,
    ORDER_DATA_QUESTION_ID,
    VENDOR_DATA_QUESTION_ID,
    WORKER_COUNT,
    PAGE_SIZE,
    CACHE_SIZE,
    city_boundaries,
)

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, 'src')
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')

# --- Initialize Flask App ---
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path='')
CORS(app)

# Enable response compression
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600  # Cache static files for 1 hour
app.config['JSON_SORT_KEYS'] = False  # Don't sort JSON keys for slightly faster response

# --- Global Data Variables ---
df_orders = None
df_vendors = None
gdf_marketing_areas = {}
gdf_tehran_region = None
gdf_tehran_main_districts = None
df_coverage_targets = None
target_lookup_dict = {}    # --- MODIFIED: Will use area_id ---
city_id_map = {1: "mashhad", 2: "tehran", 5: "shiraz"}
city_name_to_id_map = {v: k for k, v in city_id_map.items()}

# Simple cache for coverage calculations
# In-memory cache for coverage calculations. The maximum size is configured
# in ``config.py`` via ``CACHE_SIZE`` to avoid unbounded memory growth.
coverage_cache = {}

# ``city_boundaries`` used by the coverage grid is imported from ``config``.

# --- Helper Functions ---

def clean_data_for_json(data):
    """
    Recursively clean data to replace NaN, inf, and other non-JSON-serializable values with None.
    """
    if isinstance(data, dict):
        return {key: clean_data_for_json(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [clean_data_for_json(item) for item in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    elif pd.isna(data):  # Handles pandas NaN, NaT, etc.
        return None
    elif hasattr(data, 'item'):  # Handle numpy scalars
        item_val = data.item()
        if isinstance(item_val, float) and (math.isnan(item_val) or math.isinf(item_val)):
            return None
        return item_val
    else:
        return data

def safe_numeric_conversion(series, default_value=None):
    """
    Safely convert a series to numeric, replacing any problematic values with default_value.
    """
    converted = pd.to_numeric(series, errors='coerce')
    if default_value is not None:
        converted = converted.fillna(default_value)
    return converted

def safe_tolist(series):
    if series.empty:
        return []
    cleaned = series.dropna().unique()
    if pd.api.types.is_numeric_dtype(cleaned.dtype):
        return [item.item() if hasattr(item, 'item') else item for item in cleaned]
    return cleaned.tolist()

def load_tehran_shapefile(filename):
    shp_path = os.path.join(SRC_DIR, 'polygons', 'tehran_districts', filename)
    tried_encodings = [None, 'cp1256', 'utf-8']
    loaded_gdf = None
    for enc in tried_encodings:
        try:
            gdf_temp = gpd.read_file(shp_path, encoding=enc if enc else None)
            print(f"Loaded {filename} using encoding='{enc or 'default'}'")
            loaded_gdf = gdf_temp
            break
        except Exception as e:
            print(f"  • Trying encoding {enc!r} for {filename}: failed with: {e}")
    if loaded_gdf is None:
        print(f"Could not load {filename}")
        return gpd.GeoDataFrame()
    if loaded_gdf.crs and loaded_gdf.crs.to_string() != "EPSG:4326":
        try:
            loaded_gdf = loaded_gdf.to_crs("EPSG:4326")
            print(f"  • Reprojected {filename} to EPSG:4326")
        except Exception as e:
            print(f"  • Failed to reproject {filename}: {e}")
    print(f"{filename} columns: {list(loaded_gdf.columns)}")
    return loaded_gdf

def get_district_names_from_gdf(gdf, default_prefix="District"):
    if gdf is None or gdf.empty: return []
    name_cols = ['Name', 'name', 'NAME', 'Region', 'REGION_N', 'NAME_MAHAL', 'NAME_1', 'NAME_2', 'district']
    for col in name_cols:
        if col in gdf.columns and gdf[col].dtype == 'object':
            return sorted(safe_tolist(gdf[col].astype(str)))
    for col in gdf.columns: # Fallback
        if col != 'geometry' and gdf[col].dtype == 'object':
            return sorted(safe_tolist(gdf[col].astype(str)))
    return [f"{default_prefix} {i+1}" for i in range(len(gdf))]

def generate_random_points_in_polygon(poly, num_points):
    """Generates a specified number of random points within a given Shapely polygon."""
    points = []
    min_x, min_y, max_x, max_y = poly.bounds
    while len(points) < num_points:
        random_point = Point(random.uniform(min_x, max_x), random.uniform(min_y, max_y))
        if random_point.within(poly):
            points.append(random_point)
    return points

def generate_coverage_grid(city_name, grid_size_meters=200):
    """Generate a grid of points for coverage analysis."""
    if city_name not in city_boundaries:
        return []
    
    bounds = city_boundaries[city_name]
    
    # Convert grid size from meters to approximate degrees
    # At these latitudes, 1 degree ≈ 111 km
    grid_size_deg = grid_size_meters / 111000.0
    
    grid_points = []
    lat = bounds["min_lat"]
    while lat <= bounds["max_lat"]:
        lng = bounds["min_lng"]
        while lng <= bounds["max_lng"]:
            grid_points.append({"lat": lat, "lng": lng})
            lng += grid_size_deg
        lat += grid_size_deg
    
    return grid_points

def calculate_coverage_for_grid_vectorized(grid_points, df_vendors_filtered, city_name):
    """
    Calculate vendor coverage for all grid points using vectorized operations.
    Much faster than calculating point by point.
    """
    if df_vendors_filtered.empty or not grid_points:
        return []
    
    # Filter vendors with valid data
    valid_vendors = df_vendors_filtered.dropna(subset=['latitude', 'longitude', 'radius'])
    if valid_vendors.empty:
        return []
    
    # Convert to numpy arrays for faster computation
    grid_lats = np.array([p['lat'] for p in grid_points])
    grid_lngs = np.array([p['lng'] for p in grid_points])
    
    vendor_lats = valid_vendors['latitude'].values
    vendor_lngs = valid_vendors['longitude'].values
    vendor_radii = valid_vendors['radius'].values * 1000  # Convert km to meters
    
    # Pre-extract vendor attributes
    if 'business_line' in valid_vendors and isinstance(valid_vendors['business_line'].dtype, pd.CategoricalDtype):
        vendor_business_lines = valid_vendors['business_line'].cat.add_categories(['Unknown']).fillna('Unknown').values
    else:
        vendor_business_lines = valid_vendors['business_line'].fillna('Unknown').values if 'business_line' in valid_vendors else None
    if 'grade' in valid_vendors and isinstance(valid_vendors['grade'].dtype, pd.CategoricalDtype):
        vendor_grades = valid_vendors['grade'].cat.add_categories(['Unknown']).fillna('Unknown').values
    else:
        vendor_grades = valid_vendors['grade'].fillna('Unknown').values if 'grade' in valid_vendors else None
    
    coverage_results = []
    
    # Process in batches to avoid memory issues
    batch_size = 100
    for i in range(0, len(grid_points), batch_size):
        batch_end = min(i + batch_size, len(grid_points))
        batch_lats = grid_lats[i:batch_end]
        batch_lngs = grid_lngs[i:batch_end]
        
        # Vectorized distance calculation for the batch
        # Using broadcasting to calculate distances from all batch points to all vendors
        lat_diff = batch_lats[:, np.newaxis] - vendor_lats[np.newaxis, :]
        lng_diff = batch_lngs[:, np.newaxis] - vendor_lngs[np.newaxis, :]
        
        # Approximate distance in meters (good enough for our scale)
        distances_meters = np.sqrt((lat_diff * 111000)**2 + (lng_diff * 111000 * np.cos(np.radians(batch_lats[:, np.newaxis])))**2)
        
        # Check which vendors cover each point
        coverage_matrix = distances_meters <= vendor_radii[np.newaxis, :]
        
        # Process results for each point in batch
        for j, point_idx in enumerate(range(i, batch_end)):
            covering_vendors = np.where(coverage_matrix[j])[0]
            
            coverage_data = {
                "lat": grid_points[point_idx]['lat'],
                "lng": grid_points[point_idx]['lng'],
                "total_vendors": len(covering_vendors),
                "by_business_line": {},
                "by_grade": {}
            }
            
            if len(covering_vendors) > 0:
                # Count by business line
                if vendor_business_lines is not None:
                    bl_counts = {}
                    for vendor_idx in covering_vendors:
                        bl = vendor_business_lines[vendor_idx]
                        bl_counts[bl] = bl_counts.get(bl, 0) + 1
                    coverage_data["by_business_line"] = bl_counts
                
                # Count by grade
                if vendor_grades is not None:
                    grade_counts = {}
                    for vendor_idx in covering_vendors:
                        grade = vendor_grades[vendor_idx]
                        grade_counts[grade] = grade_counts.get(grade, 0) + 1
                    coverage_data["by_grade"] = grade_counts
            
            coverage_results.append(coverage_data)
    
    return coverage_results

def find_marketing_area_for_points(points, city_name):
    """
    Find which marketing area each point belongs to.
    --- FIXED: Correctly uses STRtree for efficient point-in-polygon queries. ---
    """
    if city_name not in gdf_marketing_areas or gdf_marketing_areas[city_name].empty:
        return [(None, None)] * len(points)
    gdf_areas = gdf_marketing_areas[city_name]
    results = []
    try:
        from shapely.strtree import STRtree
        area_geoms = gdf_areas.geometry.values
        area_ids = gdf_areas['area_id'].values if 'area_id' in gdf_areas else [None] * len(gdf_areas)
        area_names = gdf_areas['name'].values if 'name' in gdf_areas else [None] * len(gdf_areas)
        # Create the spatial index from the polygon geometries
        tree = STRtree(area_geoms)
        for point in points:
            point_geom = Point(point['lng'], point['lat'])
            # Step 1: Query the tree to find candidate polygons (fast BBOX intersection)
            # This returns indices of geometries whose bounding boxes intersect the point's bounding box.
            candidate_indices = tree.query(point_geom)
            found_area = False
            # Step 2: Iterate through only the candidates and perform the exact 'contains' check
            for idx in candidate_indices:
                candidate_poly = area_geoms[idx]
                if candidate_poly.contains(point_geom):
                    # Found a match!
                    results.append((area_ids[idx], area_names[idx]))
                    found_area = True
                    break  # Stop after finding the first containing polygon
            if not found_area:
                # This point was not in any of the candidate polygons
                results.append((None, None))
    except ImportError:
        # Fallback to non-indexed method (slower, but its logic was correct)
        print("Warning: shapely.strtree not found. Using slower point-in-polygon check.")
        for point in points:
            point_geom = Point(point['lng'], point['lat'])
            found = False
            for idx, area in gdf_areas.iterrows():
                if area.geometry.contains(point_geom):
                    area_id = area.get('area_id')
                    area_name = area.get('name')
                    results.append((area_id, area_name))
                    found = True
                    break
            if not found:
                results.append((None, None))
    return results

# NEW: Improved heatmap functions
def remove_outliers_and_normalize_improved(df, value_column, method='robust'):
    """
    Improved outlier removal and normalization using robust statistical methods.
    """
    if df.empty or value_column not in df.columns:
        return df
    
    df_copy = df.copy()
    df_copy = df_copy[df_copy[value_column].notna() & (df_copy[value_column] > 0)]
    
    if df_copy.empty:
        print(f"No valid {value_column} data after removing nulls/zeros")
        return df_copy
    
    values = df_copy[value_column].values
    
    if method == 'robust':
        # Use IQR method for outlier removal (more stable than percentiles)
        Q1 = np.percentile(values, 25)
        Q3 = np.percentile(values, 75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        # Keep some outliers to maintain data integrity
        lower_bound = max(lower_bound, np.percentile(values, 1))
        upper_bound = min(upper_bound, np.percentile(values, 99))
        
    elif method == 'zscore':
        # Z-score method
        z_scores = np.abs(stats.zscore(values))
        threshold = 3
        mask = z_scores < threshold
        df_copy = df_copy[mask]
        values = df_copy[value_column].values
        lower_bound = values.min()
        upper_bound = values.max()
    
    # Apply bounds
    df_copy = df_copy[(df_copy[value_column] >= lower_bound) & (df_copy[value_column] <= upper_bound)]
    
    if df_copy.empty:
        print(f"No data left after outlier removal for {value_column}")
        return df_copy
    
    # Use log transformation for better distribution
    log_values = np.log1p(df_copy[value_column])
    
    # Robust normalization using percentiles instead of min-max
    p5 = np.percentile(log_values, 5)
    p95 = np.percentile(log_values, 95)
    
    if p95 > p5:
        # Scale to 0-100 range, but cap extreme values
        normalized = ((log_values - p5) / (p95 - p5)) * 100
        normalized = np.clip(normalized, 0, 100)  # Ensure values stay in bounds
    else:
        normalized = np.full(len(df_copy), 50)
    
    df_copy[f'{value_column}_normalized'] = normalized
    
    # Also create a raw normalized version for comparison
    raw_values = df_copy[value_column].values
    raw_p5 = np.percentile(raw_values, 5)
    raw_p95 = np.percentile(raw_values, 95)
    
    if raw_p95 > raw_p5:
        raw_normalized = ((raw_values - raw_p5) / (raw_p95 - raw_p5)) * 100
        raw_normalized = np.clip(raw_normalized, 0, 100)
    else:
        raw_normalized = np.full(len(df_copy), 50)
    
    df_copy[f'{value_column}_raw_normalized'] = raw_normalized
    
    print(f"{value_column} normalization complete: {len(df_copy)} points")
    print(f"Value range: {df_copy[value_column].min():.2f} - {df_copy[value_column].max():.2f}")
    print(f"Normalized range: {normalized.min():.2f} - {normalized.max():.2f}")
    
    return df_copy

def aggregate_heatmap_points_adaptive(df, lat_col, lng_col, value_col, zoom_level=11):
    """
    Adaptive aggregation that adjusts precision based on zoom level and data density.
    """
    if df.empty:
        return df
    
    df_copy = df.copy()
    
    # Adaptive precision based on zoom level
    # Higher zoom = more precision, lower zoom = less precision
    if zoom_level >= 16:
        precision = 5  # Very fine
    elif zoom_level >= 14:
        precision = 4  # Fine
    elif zoom_level >= 12:
        precision = 3  # Medium
    elif zoom_level >= 10:
        precision = 2  # Coarse
    else:
        precision = 1  # Very coarse
    
    # Round coordinates
    df_copy['lat_rounded'] = df_copy[lat_col].round(precision)
    df_copy['lng_rounded'] = df_copy[lng_col].round(precision)
    
    # Aggregate with multiple statistics
    aggregated = df_copy.groupby(['lat_rounded', 'lng_rounded']).agg({
        value_col: ['sum', 'count', 'mean']
    }).reset_index()
    
    # Flatten column names
    aggregated.columns = ['lat', 'lng', 'value_sum', 'value_count', 'value_mean']
    
    # Use sum as primary value, but keep count for density weighting
    aggregated['value'] = aggregated['value_sum']
    aggregated['density_weight'] = np.log1p(aggregated['value_count'])  # Log scale for better distribution
    
    # Apply density weighting to reduce noise in sparse areas
    aggregated['weighted_value'] = aggregated['value'] * (1 + aggregated['density_weight'] * 0.1)
    
    return aggregated[['lat', 'lng', 'weighted_value']].rename(columns={'weighted_value': 'value'})

def aggregate_user_heatmap_points_improved(df, lat_col, lng_col, user_col, zoom_level=11):
    """
    Improved user aggregation with better handling of unique users.
    """
    if df.empty:
        return df
    
    df_copy = df.copy()
    
    # Adaptive precision
    if zoom_level >= 16:
        precision = 5
    elif zoom_level >= 14:
        precision = 4
    elif zoom_level >= 12:
        precision = 3
    else:
        precision = 2
    
    df_copy['lat_rounded'] = df_copy[lat_col].round(precision)
    df_copy['lng_rounded'] = df_copy[lng_col].round(precision)
    
    # Count unique users per location
    aggregated = df_copy.groupby(['lat_rounded', 'lng_rounded'])[user_col].nunique().reset_index()
    aggregated.columns = ['lat', 'lng', 'unique_users']
    
    # Apply log transformation for better distribution
    aggregated['value'] = np.log1p(aggregated['unique_users']) * 10  # Scale up for visibility
    
    return aggregated[['lat', 'lng', 'value']]

def generate_improved_heatmap_data(heatmap_type_req, df_orders_filtered, zoom_level=11):
    """
    Generate heatmap data using improved aggregation and normalization.
    """
    heatmap_data = []
    
    if heatmap_type_req not in ["order_density", "order_density_organic", "order_density_non_organic", "user_density"]:
        return heatmap_data
    
    df_hm_source = df_orders_filtered.dropna(subset=['customer_latitude', 'customer_longitude'])
    if df_hm_source.empty:
        return heatmap_data
    
    if heatmap_type_req == "order_density":
        df_hm_source['order_count'] = 1
        df_aggregated = aggregate_heatmap_points_adaptive(
            df_hm_source, 'customer_latitude', 'customer_longitude', 'order_count', zoom_level
        )
    elif heatmap_type_req == "order_density_organic":
        if 'organic' in df_hm_source.columns:
            df_organic = df_hm_source[df_hm_source['organic'] == 1]
            if not df_organic.empty:
                df_aggregated = aggregate_heatmap_points_adaptive(
                    df_organic.assign(order_count=1), 'customer_latitude', 'customer_longitude', 'order_count', zoom_level
                )
            else:
                df_aggregated = pd.DataFrame(columns=['lat', 'lng', 'value'])
        else:
            df_aggregated = pd.DataFrame(columns=['lat', 'lng', 'value'])
    elif heatmap_type_req == "order_density_non_organic":
        if 'organic' in df_hm_source.columns:
            df_non_organic = df_hm_source[df_hm_source['organic'] == 0]
            if not df_non_organic.empty:
                df_aggregated = aggregate_heatmap_points_adaptive(
                    df_non_organic.assign(order_count=1), 'customer_latitude', 'customer_longitude', 'order_count', zoom_level
                )
            else:
                df_aggregated = pd.DataFrame(columns=['lat', 'lng', 'value'])
        else:
            df_aggregated = pd.DataFrame(columns=['lat', 'lng', 'value'])
    elif heatmap_type_req == "user_density":
        if 'user_id' in df_hm_source.columns:
            df_aggregated = aggregate_user_heatmap_points_improved(
                df_hm_source, 'customer_latitude', 'customer_longitude', 'user_id', zoom_level
            )
        else:
            df_aggregated = pd.DataFrame(columns=['lat', 'lng', 'value'])
    
    # Apply improved normalization
    if not df_aggregated.empty:
        df_normalized = remove_outliers_and_normalize_improved(df_aggregated, 'value', method='robust')
        if not df_normalized.empty:
            # Use the normalized values
            df_normalized['value'] = df_normalized['value_normalized']
            heatmap_data = df_normalized[['lat', 'lng', 'value']].to_dict(orient='records')
    
    return heatmap_data

def generate_basic_heatmap_fallback(heatmap_type_req, df_orders_filtered):
    """
    Fallback method using the original heatmap generation logic.
    """
    try:
        df_hm_source = df_orders_filtered.dropna(subset=['customer_latitude', 'customer_longitude'])
        if df_hm_source.empty:
            return []
        
        if heatmap_type_req == "order_density":
            df_hm_source['order_count'] = 1
            df_aggregated = aggregate_heatmap_points(df_hm_source, 'customer_latitude', 'customer_longitude', 'order_count', precision=4)
        elif heatmap_type_req == "order_density_organic":
            if 'organic' in df_hm_source.columns:
                df_organic = df_hm_source[df_hm_source['organic'] == 1]
                df_aggregated = aggregate_heatmap_points(df_organic.assign(order_count=1), 'customer_latitude', 'customer_longitude', 'order_count', precision=4) if not df_organic.empty else pd.DataFrame(columns=['lat', 'lng', 'value'])
            else: 
                df_aggregated = pd.DataFrame(columns=['lat', 'lng', 'value'])
        elif heatmap_type_req == "order_density_non_organic":
            if 'organic' in df_hm_source.columns:
                df_non_organic = df_hm_source[df_hm_source['organic'] == 0]
                df_aggregated = aggregate_heatmap_points(df_non_organic.assign(order_count=1), 'customer_latitude', 'customer_longitude', 'order_count', precision=4) if not df_non_organic.empty else pd.DataFrame(columns=['lat', 'lng', 'value'])
            else: 
                df_aggregated = pd.DataFrame(columns=['lat', 'lng', 'value'])
        elif heatmap_type_req == "user_density":
            df_aggregated = aggregate_user_heatmap_points(df_hm_source, 'customer_latitude', 'customer_longitude', 'user_id', precision=4) if 'user_id' in df_hm_source.columns else pd.DataFrame(columns=['lat', 'lng', 'value'])
        
        if not df_aggregated.empty and heatmap_type_req != "user_density":
            max_count = df_aggregated['value'].max()
            min_count = df_aggregated['value'].min()
            df_aggregated['value'] = ((df_aggregated['value'] - min_count) / (max_count - min_count)) * 100 if max_count > min_count else 50
        
        return df_aggregated.to_dict(orient='records')
        
    except Exception as e:
        print(f"Error in fallback heatmap generation: {e}")
        return []

# LEGACY: Keep original functions for backward compatibility
def remove_outliers_and_normalize(df, value_column, lower_percentile=5, upper_percentile=95):
    """
    Remove outliers using percentile method and normalize values to 0-100 range.
    Returns a copy of the dataframe with normalized values.
    """
    if df.empty or value_column not in df.columns:
        return df
    
    # Create a copy to avoid modifying the original
    df_copy = df.copy()
    
    # Remove rows where the value is null or zero
    df_copy = df_copy[df_copy[value_column].notna() & (df_copy[value_column] > 0)]
    
    if df_copy.empty:
        print(f"No valid {value_column} data after removing nulls/zeros")
        return df_copy
    
    # Calculate percentiles for outlier removal
    lower_bound = df_copy[value_column].quantile(lower_percentile / 100)
    upper_bound = df_copy[value_column].quantile(upper_percentile / 100)
    
    print(f"{value_column} bounds: {lower_bound:,.0f} to {upper_bound:,.0f}")
    
    # Remove outliers
    df_copy = df_copy[(df_copy[value_column] >= lower_bound) & (df_copy[value_column] <= upper_bound)]
    
    if df_copy.empty:
        print(f"No data left after outlier removal for {value_column}")
        return df_copy
    
    # Normalize to 0-100 range
    min_val = df_copy[value_column].min()
    max_val = df_copy[value_column].max()
    
    if max_val > min_val:
        df_copy[f'{value_column}_normalized'] = ((df_copy[value_column] - min_val) / (max_val - min_val)) * 100
    else:
        df_copy[f'{value_column}_normalized'] = 50  # If all values are the same, set to middle value
    
    # Log transformation for better distribution (optional, helps with skewed data)
    # This helps when you have many small values and few large values
    df_copy[f'{value_column}_log_normalized'] = np.log1p(df_copy[value_column])
    log_min = df_copy[f'{value_column}_log_normalized'].min()
    log_max = df_copy[f'{value_column}_log_normalized'].max()
    
    if log_max > log_min:
        df_copy[f'{value_column}_log_normalized'] = ((df_copy[f'{value_column}_log_normalized'] - log_min) / (log_max - log_min)) * 100
    else:
        df_copy[f'{value_column}_log_normalized'] = 50
    
    print(f"{value_column} normalization complete: {len(df_copy)} points")
    return df_copy

def aggregate_heatmap_points(df, lat_col, lng_col, value_col, precision=None):
    """
    Aggregate heatmap points by rounding coordinates to create heat accumulation.
    This ensures areas with multiple orders show more heat.
    """
    if df.empty:
        return df
    
    # Create a copy to avoid modifying the original
    df_copy = df.copy()
    
    # Round coordinates to aggregate nearby points
    df_copy['lat_rounded'] = df_copy[lat_col].round(precision)
    df_copy['lng_rounded'] = df_copy[lng_col].round(precision)
    
    # Aggregate values for the same rounded location
    aggregated = df_copy.groupby(['lat_rounded', 'lng_rounded']).agg({
        value_col: 'sum'
    }).reset_index()
    
    # Rename columns to standard names for output
    aggregated['lat'] = aggregated['lat_rounded']
    aggregated['lng'] = aggregated['lng_rounded']
    aggregated['value'] = aggregated[value_col]
    
    return aggregated[['lat', 'lng', 'value']]

def aggregate_user_heatmap_points(df, lat_col, lng_col, user_col, precision=4):
    """
    Aggregate unique users by location for user heatmap.
    """
    if df.empty:
        return df
    
    # Create a copy
    df_copy = df.copy()
    
    # Round coordinates
    df_copy['lat_rounded'] = df_copy[lat_col].round(precision)
    df_copy['lng_rounded'] = df_copy[lng_col].round(precision)
    
    # Count unique users per location
    aggregated = df_copy.groupby(['lat_rounded', 'lng_rounded'])[user_col].nunique().reset_index()
    
    # Rename columns
    aggregated['lat'] = aggregated['lat_rounded']
    aggregated['lng'] = aggregated['lng_rounded']
    aggregated['value'] = aggregated[user_col]
    
    # Normalize values
    if len(aggregated) > 0:
        max_val = aggregated['value'].max()
        min_val = aggregated['value'].min()
        if max_val > min_val:
            aggregated['value'] = ((aggregated['value'] - min_val) / (max_val - min_val)) * 100
        else:
            aggregated['value'] = 50
    
    return aggregated[['lat', 'lng', 'value']]

def load_data():
    """Load all required datasets from Metabase and local sources.

    This function populates global data frames used by the API layer. It is
    executed at start-up both in development and production environments.
    """
    global df_orders, df_vendors, gdf_marketing_areas, gdf_tehran_region, gdf_tehran_main_districts, df_coverage_targets, target_lookup_dict
    print("Loading data...")
    start_time = time.time()
    try:
        # Specify dtypes to reduce memory usage and speed up loading
        dtype_dict = {
            'city_id': 'Int64',
            'business_line': 'category',
            'marketing_area': 'category',
            'vendor_code': 'str',
            'organic': 'int8'
        }
        
        print(f"🚀 Fetching LIVE order data from Metabase Question ID: {ORDER_DATA_QUESTION_ID}...")
        df_orders = fetch_question_data(
            question_id=ORDER_DATA_QUESTION_ID,
            metabase_url=METABASE_URL,
            username=METABASE_USERNAME,
            password=METABASE_PASSWORD
        )
        df_orders = df_orders.astype(dtype_dict)
        df_orders['created_at'] = pd.to_datetime(df_orders['created_at'], errors='coerce')
        df_orders['created_at'] = df_orders['created_at'].dt.tz_localize(None)
        df_orders['city_name'] = df_orders['city_id'].map(city_id_map).astype('category')
        
        if 'organic' not in df_orders.columns:
            # If organic column doesn't exist, create a random one for demo
            df_orders['organic'] = np.random.choice([0, 1], size=len(df_orders), p=[0.7, 0.3]).astype('int8')
                
        print(f"Orders loaded: {len(df_orders)} rows in {time.time() - start_time:.2f}s")
    except Exception as e:
        print(f"Error loading order data: {e}")
        df_orders = pd.DataFrame()
        
    # 2. Vendor Data
    graded_file = os.path.join(SRC_DIR, 'vendor', 'graded.csv')
    try:
        vendor_start = time.time()
        # Optimize dtypes for vendors too
        vendor_dtype = {
            'city_id': 'Int64',
            'vendor_code': 'str',
            'status_id': 'float32',
            'visible': 'float32',
            'open': 'float32',
            'radius': 'float32',
            'business_line': 'category'  # ADDED: Ensure business_line is treated as category
        }
        
        print(f"🚀 Fetching LIVE vendor data from Metabase Question ID: {VENDOR_DATA_QUESTION_ID}...")
        df_vendors_raw = fetch_question_data(
            question_id=VENDOR_DATA_QUESTION_ID,
            metabase_url=METABASE_URL,
            username=METABASE_USERNAME,
            password=METABASE_PASSWORD
        )
        df_vendors_raw = df_vendors_raw.astype(vendor_dtype)
        df_vendors_raw['city_name'] = df_vendors_raw['city_id'].map(city_id_map).astype('category')
        
        # MODIFIED: Use the business_line from df_vendors directly, don't override it
        df_vendors = df_vendors_raw.copy()
        
        # Debug: Print business line info
        if 'business_line' in df_vendors.columns:
            print(f"Business lines in vendors: {sorted(df_vendors['business_line'].unique())}")
            print(f"Business line counts: {df_vendors['business_line'].value_counts()}")
        else:
            print("WARNING: business_line column not found in vendor data!")
        
        try:
            df_graded_data = pd.read_csv(graded_file, dtype={'vendor_code': 'str', 'grade': 'category'})
            if 'vendor_code' in df_vendors.columns and 'vendor_code' in df_graded_data.columns:
                df_vendors['vendor_code'] = df_vendors['vendor_code'].astype(str)
                df_graded_data['vendor_code'] = df_graded_data['vendor_code'].astype(str)
                df_vendors = pd.merge(df_vendors, df_graded_data[['vendor_code', 'grade']], on='vendor_code', how='left')
                if 'grade' in df_vendors.columns and isinstance(df_vendors['grade'].dtype, pd.CategoricalDtype):
                    df_vendors['grade'] = df_vendors['grade'].cat.add_categories(['Ungraded'])
                df_vendors['grade'] = df_vendors['grade'].fillna('Ungraded').astype('category')
                print(f"Grades loaded and merged. Found {df_vendors['grade'].notna().sum()} graded vendors.")
            else:
                print("Warning: 'vendor_code' column missing in vendors or graded CSV. Grades not merged.")
                if 'grade' not in df_vendors.columns: 
                    df_vendors['grade'] = pd.Categorical(['Ungraded'] * len(df_vendors))
        except Exception as eg:
            print(f"Error loading or merging graded.csv: {eg}. Proceeding without grades.")
            if 'grade' not in df_vendors.columns: 
                df_vendors['grade'] = pd.Categorical(['Ungraded'] * len(df_vendors))
        
        # REMOVED: Don't override business_line from orders - use the one from vendors directly
        
        for col in ['latitude', 'longitude', 'vendor_name', 'radius', 'status_id', 'visible', 'open', 'vendor_code']:
            if col not in df_vendors.columns: df_vendors[col] = np.nan
            
        # FIX: Proper NaN handling for numeric columns
        if 'visible' in df_vendors.columns: 
            df_vendors['visible'] = safe_numeric_conversion(df_vendors['visible'])
        if 'open' in df_vendors.columns: 
            df_vendors['open'] = safe_numeric_conversion(df_vendors['open'])
        if 'status_id' in df_vendors.columns: 
            df_vendors['status_id'] = safe_numeric_conversion(df_vendors['status_id'])
        if 'latitude' in df_vendors.columns: 
            df_vendors['latitude'] = safe_numeric_conversion(df_vendors['latitude'])
        if 'longitude' in df_vendors.columns: 
            df_vendors['longitude'] = safe_numeric_conversion(df_vendors['longitude'])
        if 'radius' in df_vendors.columns: 
            df_vendors['radius'] = safe_numeric_conversion(df_vendors['radius'])
        if 'vendor_code' in df_vendors.columns: 
            df_vendors['vendor_code'] = df_vendors['vendor_code'].astype(str)
        
        # Store original radius for reset functionality
        if 'radius' in df_vendors.columns:
            df_vendors['original_radius'] = df_vendors['radius'].copy()
            
        print(f"Vendors loaded: {len(df_vendors)} rows in {time.time() - vendor_start:.2f}s")
    except Exception as e:
        print(f"Error loading vendor data: {e}")
        df_vendors = pd.DataFrame()
        if df_vendors is not None and 'grade' not in df_vendors.columns: 
            df_vendors['grade'] = pd.Categorical(['Ungraded'] * len(df_vendors))
    
    # 3. Polygon Data - Load in parallel if possible
    poly_start = time.time()
    marketing_areas_base = os.path.join(SRC_DIR, 'polygons', 'tapsifood_marketing_areas')
    tehran_area_name_to_id_map = {}
    for city_file_name in ['mashhad_polygons.csv', 'tehran_polygons.csv', 'shiraz_polygons.csv']:
        city_name_key = city_file_name.split('_')[0]
        file_path = os.path.join(marketing_areas_base, city_file_name)
        try:
            df_poly = pd.read_csv(file_path, encoding='utf-8')
            if 'WKT' not in df_poly.columns: df_poly['WKT'] = None
            df_poly['geometry'] = df_poly['WKT'].apply(lambda x: wkt.loads(x) if pd.notna(x) else None)
            
            # --- NEW: Add a unique, stable ID for robust matching ---
            df_poly['area_id'] = f"{city_name_key}_" + df_poly.index.astype(str)
            
            if 'name' not in df_poly.columns: 
                df_poly['name'] = [f"{city_name_key}_area_{i+1}" for i in range(len(df_poly))]
            else:
                df_poly['name'] = df_poly['name'].astype(str).str.strip().astype('category')
            
            gdf = gpd.GeoDataFrame(df_poly, geometry='geometry', crs="EPSG:4326").dropna(subset=['geometry'])
            gdf_marketing_areas[city_name_key] = gdf
            
            # If this is Tehran, create the name -> id map for the target CSV
            if city_name_key == 'tehran':
                tehran_area_name_to_id_map = gdf.set_index('name')['area_id'].to_dict()
                print(f"DEBUG: Created Tehran area name-to-id map with {len(tehran_area_name_to_id_map)} entries.")
            print(f"Marketing areas for {city_name_key} loaded: {len(gdf_marketing_areas[city_name_key])} polygons")
        except Exception as e:
            print(f"Error loading marketing areas for {city_name_key} from {file_path}: {e}")
            gdf_marketing_areas[city_name_key] = gpd.GeoDataFrame()
    
    # --- NEW: Load and process tehran_coverage.csv ---
    coverage_target_file = os.path.join(SRC_DIR, 'targets', 'tehran_coverage.csv')
    try:
        df_temp_targets = pd.read_csv(coverage_target_file, encoding='utf-8')
        if 'marketing_area' in df_temp_targets.columns:
            df_temp_targets['marketing_area'] = df_temp_targets['marketing_area'].str.strip()
            
            # --- NEW: Map area names to the newly created area_ids ---
            df_temp_targets['area_id'] = df_temp_targets['marketing_area'].map(tehran_area_name_to_id_map)
            
            # --- DEBUG: Check for mismatches ---
            unmapped_areas = df_temp_targets[df_temp_targets['area_id'].isna()]
            if not unmapped_areas.empty:
                print(f"!!! WARNING: Could not map {len(unmapped_areas['marketing_area'].unique())} areas from tehran_coverage.csv to polygon IDs.")
                print(f"--- Mismatched Names: {unmapped_areas['marketing_area'].unique().tolist()}")
            
            df_temp_targets.dropna(subset=['area_id'], inplace=True) # Drop targets that can't be mapped
            # Melt the dataframe to a long format
            df_coverage_targets = df_temp_targets.melt(
                id_vars=['area_id', 'marketing_area'], # keep both for reference
                var_name='business_line',
                value_name='target'
            )
            
            # --- MODIFIED: Create a dictionary using area_id for robust, fast lookups ---
            target_lookup_dict = df_coverage_targets.set_index(['area_id', 'business_line'])['target'].to_dict()
            print(f"DEBUG: Tehran coverage target lookup created. Keys format: (area_id, business_line).")
            print(f"--- Total mapped targets: {len(target_lookup_dict)}")
            # Print a sample key-value pair for verification
            if target_lookup_dict:
                 print(f"--- Sample lookup entry: {next(iter(target_lookup_dict.items()))}")
        else:
            print("Warning: 'marketing_area' column not found in tehran_coverage.csv. Targets not loaded.")
            df_coverage_targets = pd.DataFrame()
    except Exception as e:
        print(f"Error loading tehran_coverage.csv: {e}")
        df_coverage_targets = pd.DataFrame()
    
    gdf_tehran_region = load_tehran_shapefile('RegionTehran_WGS1984.shp')
    gdf_tehran_main_districts = load_tehran_shapefile('Tehran_WGS1984.shp')
    
    total_time = time.time() - start_time
    print(f"Data loading complete in {total_time:.2f} seconds.")

# --- Serve Static Files (Frontend) ---
@app.route('/')
def serve_index():
    return send_from_directory(PUBLIC_DIR, 'index.html')

@app.route('/api/initial-data', methods=['GET'])
def get_initial_data():
    if df_orders is None or df_vendors is None:
        return jsonify({"error": "Data not loaded properly"}), 500
    
    cities = [{"id": cid, "name": name} for cid, name in city_id_map.items()]
    business_lines = []
    if not df_orders.empty and 'business_line' in df_orders.columns:
        business_lines = safe_tolist(df_orders['business_line'])
    
    marketing_area_names_by_city = {}
    for city_key, gdf in gdf_marketing_areas.items():
        if not gdf.empty and 'name' in gdf.columns:
            marketing_area_names_by_city[city_key] = sorted(safe_tolist(gdf['name'].astype(str)))
        else: 
            marketing_area_names_by_city[city_key] = []
    
    tehran_region_districts = get_district_names_from_gdf(gdf_tehran_region, "Region Tehran")
    tehran_main_districts = get_district_names_from_gdf(gdf_tehran_main_districts, "Main Tehran")
    
    vendor_statuses = []
    if not df_vendors.empty and 'status_id' in df_vendors.columns:
        # Filter out NaN values before converting to int
        status_series = df_vendors['status_id'].dropna()
        if not status_series.empty:
            vendor_statuses = sorted([int(x) for x in status_series.unique()])
    
    vendor_grades = []
    if not df_vendors.empty and 'grade' in df_vendors.columns:
        vendor_grades = sorted(safe_tolist(df_vendors['grade'].astype(str)))
    
    return jsonify({
        "cities": cities,
        "business_lines": business_lines,
        "marketing_areas_by_city": marketing_area_names_by_city,
        "tehran_region_districts": tehran_region_districts,
        "tehran_main_districts": tehran_main_districts,
        "vendor_statuses": vendor_statuses,
        "vendor_grades": vendor_grades
    })

def enrich_polygons_with_stats(gdf_polygons, name_col, df_v_filtered, df_o_filtered, df_o_all_for_city):
    """
    Enriches a polygon GeoDataFrame with vendor and user statistics.
    Args:
        gdf_polygons (gpd.GeoDataFrame): The polygons to enrich.
        name_col (str): The name of the unique identifier column in the polygon GDF.
        df_v_filtered (pd.DataFrame): Pre-filtered vendor data.
        df_o_filtered (pd.DataFrame): Pre-filtered order data (by date, bl, etc.).
        df_o_all_for_city (pd.DataFrame): Order data filtered only by city (for total user count).
    Returns:
        gpd.GeoDataFrame: The enriched GeoDataFrame.
    """
    if gdf_polygons is None or gdf_polygons.empty:
        return gpd.GeoDataFrame()
    enriched_gdf = gdf_polygons.copy()
    # --- 1. Vendor Enrichment ---
    if not df_v_filtered.empty and not df_v_filtered.dropna(subset=['latitude', 'longitude']).empty:
        gdf_v_filtered_for_enrich = gpd.GeoDataFrame(
            df_v_filtered.dropna(subset=['latitude', 'longitude']),
            geometry=gpd.points_from_xy(df_v_filtered.longitude, df_v_filtered.latitude),
            crs="EPSG:4326"
        )
        joined_vendors = gpd.sjoin(gdf_v_filtered_for_enrich, enriched_gdf, how="inner", predicate="within")
        # Total vendor count
        vendor_counts = joined_vendors.groupby(name_col).size().rename('vendor_count')
        enriched_gdf = enriched_gdf.merge(vendor_counts, how='left', left_on=name_col, right_index=True)
        # Vendor count by grade
        if 'grade' in joined_vendors.columns:
            grade_counts_series = joined_vendors.groupby([name_col, 'grade'], observed=True).size().unstack(fill_value=0)
            grade_counts_dict = grade_counts_series.apply(lambda row: {k: v for k, v in row.items() if v > 0}, axis=1).to_dict()
            enriched_gdf['grade_counts'] = enriched_gdf[name_col].astype(str).map(grade_counts_dict)
        else:
             enriched_gdf['grade_counts'] = None
    else:
        enriched_gdf['vendor_count'] = 0
        enriched_gdf['grade_counts'] = None
    
    enriched_gdf['vendor_count'] = enriched_gdf['vendor_count'].fillna(0).astype(int)
    # --- 2. Unique User Enrichment (Date-Ranged & Total) ---
    has_user_id = 'user_id' in df_o_all_for_city.columns
    if has_user_id:
        # A) Date-Ranged Unique Users
        if not df_o_filtered.empty and not df_o_filtered.dropna(subset=['customer_latitude', 'customer_longitude']).empty:
            gdf_orders_filtered = gpd.GeoDataFrame(
                df_o_filtered.dropna(subset=['customer_latitude', 'customer_longitude']),
                geometry=gpd.points_from_xy(df_o_filtered.customer_longitude, df_o_filtered.customer_latitude),
                crs="EPSG:4326"
            )
            joined_orders_filtered = gpd.sjoin(gdf_orders_filtered, enriched_gdf, how="inner", predicate="within")
            user_counts_filtered = joined_orders_filtered.groupby(name_col, observed=True)['user_id'].nunique().rename('unique_user_count')
            enriched_gdf = enriched_gdf.merge(user_counts_filtered, how='left', left_on=name_col, right_index=True)
        
        # B) Total (All-Time) Unique Users for the city
        if not df_o_all_for_city.empty and not df_o_all_for_city.dropna(subset=['customer_latitude', 'customer_longitude']).empty:
            gdf_orders_all = gpd.GeoDataFrame(
                df_o_all_for_city.dropna(subset=['customer_latitude', 'customer_longitude']),
                geometry=gpd.points_from_xy(df_o_all_for_city.customer_longitude, df_o_all_for_city.customer_latitude),
                crs="EPSG:4326"
            )
            joined_orders_all = gpd.sjoin(gdf_orders_all, enriched_gdf, how="inner", predicate="within")
            user_counts_all = joined_orders_all.groupby(name_col, observed=True)['user_id'].nunique().rename('total_unique_user_count')
            enriched_gdf = enriched_gdf.merge(user_counts_all, how='left', left_on=name_col, right_index=True)
    enriched_gdf['unique_user_count'] = enriched_gdf.get('unique_user_count', pd.Series(0, index=enriched_gdf.index)).fillna(0).astype(int)
    enriched_gdf['total_unique_user_count'] = enriched_gdf.get('total_unique_user_count', pd.Series(0, index=enriched_gdf.index)).fillna(0).astype(int)
    
    # --- 3. Population-based Metrics (if Pop data exists) ---
    if 'Pop' in enriched_gdf.columns:
        enriched_gdf['Pop'] = safe_numeric_conversion(enriched_gdf['Pop'], 0)
        enriched_gdf['vendor_per_10k_pop'] = enriched_gdf.apply(
            lambda row: (row['vendor_count'] / row['Pop']) * 10000 if row['Pop'] > 0 else 0, axis=1
        )
    if 'PopDensity' in enriched_gdf.columns:
        enriched_gdf['PopDensity'] = safe_numeric_conversion(enriched_gdf['PopDensity'], 0)
        
    return enriched_gdf

@app.route('/api/map-data', methods=['GET'])
def get_map_data():
    if df_orders is None or df_vendors is None:
        return jsonify({"error": "Server data not loaded"}), 500
    try:
        # Start timing
        request_start = time.time()
        
        # --- Parsing of filters ---
        city_name = request.args.get('city', default="tehran", type=str)
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        start_date = pd.to_datetime(start_date_str) if start_date_str else None
        end_date = pd.to_datetime(end_date_str).replace(hour=23, minute=59, second=59) if end_date_str else None
        selected_business_lines = [bl.strip() for bl in request.args.getlist('business_lines') if bl.strip()]
        vendor_codes_input_str = request.args.get('vendor_codes_filter', default="", type=str)
        selected_vendor_codes_for_vendors_only = [code.strip() for code in re.split(r'[\s,;\n]+', vendor_codes_input_str) if code.strip()]
        selected_vendor_status_ids = [int(s.strip()) for s in request.args.getlist('vendor_status_ids') if s.strip().isdigit()]
        selected_vendor_grades = [g.strip() for g in request.args.getlist('vendor_grades') if g.strip()]
        vendor_visible_str = request.args.get('vendor_visible', default="any", type=str)
        vendor_is_open_str = request.args.get('vendor_is_open', default="any", type=str)
        vendor_area_main_type = request.args.get('vendor_area_main_type', default="all", type=str)
        selected_vendor_area_sub_types = [s.strip() for s in request.args.getlist('vendor_area_sub_type') if s.strip()]
        heatmap_type_req = request.args.get('heatmap_type_request', default="none", type=str)
        area_type_display = request.args.get('area_type_display', default="tapsifood_marketing_areas", type=str)
        selected_polygon_sub_types = [s.strip() for s in request.args.getlist('area_sub_type_filter') if s.strip()]
        
        # NEW: Get zoom level for adaptive heatmap processing
        zoom_level = request.args.get('zoom_level', default=11, type=float)
        
        # Radius modifier parameters
        radius_modifier = request.args.get('radius_modifier', default=1.0, type=float)
        radius_mode = request.args.get('radius_mode', default='percentage', type=str)
        radius_fixed = request.args.get('radius_fixed', default=3.0, type=float)
        
        # DEBUG: Print filter info
        print(f"DEBUG: Business line filter = {selected_business_lines}")
        print(f"DEBUG: Total vendors before filtering = {len(df_vendors)}")
        
        heatmap_data = []
        vendor_markers = []
        polygons_geojson = {"type": "FeatureCollection", "features": []}
        coverage_grid_data = []
        
        # --- IMPROVED Vendor filtering logic with better debugging ---
        df_v_filtered = df_vendors.copy()
        
        # Check if required columns exist
        required_vendor_columns = ['latitude', 'longitude', 'vendor_code']
        missing_columns = [col for col in required_vendor_columns if col not in df_v_filtered.columns]
        if missing_columns:
            print(f"Warning: Missing vendor columns: {missing_columns}")
            vendor_markers = []
        else:
            # 1. Apply radius modifier based on mode - FIX: Handle NaN values properly
            if 'radius' in df_v_filtered.columns and 'original_radius' in df_v_filtered.columns:
                if radius_mode == 'fixed':
                    df_v_filtered['radius'] = radius_fixed
                else:
                    # Handle NaN values in original_radius
                    df_v_filtered['radius'] = df_v_filtered['original_radius'].fillna(3.0) * radius_modifier
            
            # 2. Remove vendors with invalid coordinates
            df_v_filtered = df_v_filtered.dropna(subset=['latitude', 'longitude', 'vendor_code'])
            print(f"DEBUG: Vendors after coordinate filtering = {len(df_v_filtered)}")
            
            # 3. Filter by city
            if city_name != "all" and 'city_name' in df_v_filtered.columns: 
                df_v_filtered = df_v_filtered[df_v_filtered['city_name'] == city_name]
                print(f"DEBUG: Vendors after city filtering ({city_name}) = {len(df_v_filtered)}")
            
            # 4. EARLY BUSINESS LINE FILTERING - Apply this before area filtering
            if selected_business_lines and 'business_line' in df_v_filtered.columns:
                print(f"DEBUG: Available business lines in vendors: {sorted(df_v_filtered['business_line'].unique())}")
                df_v_filtered = df_v_filtered[df_v_filtered['business_line'].isin(selected_business_lines)]
                print(f"DEBUG: Vendors after business line filtering = {len(df_v_filtered)}")
            
            # 5. Filter by specific vendor codes
            if selected_vendor_codes_for_vendors_only and 'vendor_code' in df_v_filtered.columns: 
                df_v_filtered = df_v_filtered[df_v_filtered['vendor_code'].astype(str).isin(selected_vendor_codes_for_vendors_only)]
                print(f"DEBUG: Vendors after vendor code filtering = {len(df_v_filtered)}")
            
            # 6. Filter by vendor area (spatial filtering)
            if vendor_area_main_type != 'all' and selected_vendor_area_sub_types and not df_v_filtered.empty:
                if vendor_area_main_type == 'tapsifood_marketing_areas' and not df_orders.empty and 'marketing_area' in df_orders.columns:
                    temp_orders_ma = df_orders[df_orders['marketing_area'].isin(selected_vendor_area_sub_types)]
                    relevant_vendor_codes_ma = temp_orders_ma['vendor_code'].astype(str).dropna().unique()
                    df_v_filtered = df_v_filtered[df_v_filtered['vendor_code'].isin(relevant_vendor_codes_ma)]
                elif city_name == 'tehran':
                    target_gdf = None
                    if vendor_area_main_type == 'tehran_region_districts': target_gdf = gdf_tehran_region.copy() if gdf_tehran_region is not None else None
                    elif vendor_area_main_type == 'tehran_main_districts': target_gdf = gdf_tehran_main_districts.copy() if gdf_tehran_main_districts is not None else None
                    if target_gdf is not None and not target_gdf.empty:
                        name_col = next((col for col in ['Name', 'NAME_MAHAL'] if col in target_gdf.columns), None)
                        if name_col: target_gdf = target_gdf[target_gdf[name_col].isin(selected_vendor_area_sub_types)]
                        if not target_gdf.empty:
                            gdf_vendors_to_filter = gpd.GeoDataFrame(df_v_filtered, geometry=gpd.points_from_xy(df_v_filtered.longitude, df_v_filtered.latitude), crs="EPSG:4326")
                            vendors_in_area = gpd.sjoin(gdf_vendors_to_filter, target_gdf, how="inner", predicate="within")
                            codes_in_area = vendors_in_area['vendor_code'].unique() if not vendors_in_area.empty else []
                            df_v_filtered = df_v_filtered[df_v_filtered['vendor_code'].isin(codes_in_area)]
                print(f"DEBUG: Vendors after area filtering = {len(df_v_filtered)}")
            
            # 7. Apply other vendor filters
            if not df_v_filtered.empty:
                if selected_vendor_status_ids and 'status_id' in df_v_filtered.columns: 
                    df_v_filtered = df_v_filtered[df_v_filtered['status_id'].isin(selected_vendor_status_ids)]
                    print(f"DEBUG: Vendors after status filtering = {len(df_v_filtered)}")
                if selected_vendor_grades and 'grade' in df_v_filtered.columns: 
                    df_v_filtered = df_v_filtered[df_v_filtered['grade'].isin(selected_vendor_grades)]
                    print(f"DEBUG: Vendors after grade filtering = {len(df_v_filtered)}")
                if vendor_visible_str != "any" and 'visible' in df_v_filtered.columns: 
                    df_v_filtered = df_v_filtered[df_v_filtered['visible'] == int(vendor_visible_str)]
                    print(f"DEBUG: Vendors after visible filtering = {len(df_v_filtered)}")
                if vendor_is_open_str != "any" and 'open' in df_v_filtered.columns: 
                    df_v_filtered = df_v_filtered[df_v_filtered['open'] == int(vendor_is_open_str)]
                    print(f"DEBUG: Vendors after open filtering = {len(df_v_filtered)}")
            
            if not df_v_filtered.empty:
                # FIX: Clean data before converting to dict
                vendor_markers = clean_data_for_json(df_v_filtered.to_dict(orient='records'))
                print(f"DEBUG: Final vendor count for map = {len(vendor_markers)}")
            else:
                vendor_markers = []
                print("DEBUG: No vendors after filtering")
        
        # --- Prepare filtered and total order dataframes for enrichment ---
        df_orders_filtered = df_orders.copy()
        if city_name != "all": df_orders_filtered = df_orders_filtered[df_orders_filtered['city_name'] == city_name]
        df_orders_all_for_city = df_orders_filtered.copy()
        if start_date: df_orders_filtered = df_orders_filtered[df_orders_filtered['created_at'] >= start_date]
        if end_date: df_orders_filtered = df_orders_filtered[df_orders_filtered['created_at'] <= end_date]
        if selected_business_lines: df_orders_filtered = df_orders_filtered[df_orders_filtered['business_line'].isin(selected_business_lines)]
        
        # --- IMPROVED Heatmap generation using new functions ---
        if heatmap_type_req in ["order_density", "order_density_organic", "order_density_non_organic", "user_density"]:
            print(f"Generating improved heatmap for type: {heatmap_type_req} at zoom level: {zoom_level}")
            
            try:
                heatmap_data_result = generate_improved_heatmap_data(heatmap_type_req, df_orders_filtered, zoom_level)
                
                if heatmap_data_result:
                    # Add metadata for frontend optimization
                    print(f"Generated {len(heatmap_data_result)} heatmap points")
                    
                    # Calculate some statistics for the frontend
                    values = [point['value'] for point in heatmap_data_result if 'value' in point and point['value'] is not None]
                    if values:
                        heatmap_stats = {
                            'count': len(values),
                            'min': float(np.min(values)),
                            'max': float(np.max(values)),
                            'mean': float(np.mean(values)),
                            'p75': float(np.percentile(values, 75)),
                            'p90': float(np.percentile(values, 90)),
                            'p95': float(np.percentile(values, 95))
                        }
                        print(f"Heatmap stats: {heatmap_stats}")
                    
                    heatmap_data = heatmap_data_result
                else:
                    print("No heatmap data generated")
                    heatmap_data = []
                    
            except Exception as e:
                print(f"Error generating improved heatmap: {e}")
                # Fallback to basic method if improved method fails
                heatmap_data = generate_basic_heatmap_fallback(heatmap_type_req, df_orders_filtered)
        
        elif heatmap_type_req == "population" and city_name == "tehran":
            print("Generating population heatmap...")
            gdf_pop_source = None
            if area_type_display == "tehran_main_districts" and gdf_tehran_main_districts is not None: 
                gdf_pop_source = gdf_tehran_main_districts
            elif area_type_display == "tehran_region_districts" and gdf_tehran_region is not None: 
                gdf_pop_source = gdf_tehran_region
            elif area_type_display == "all_tehran_districts" and gdf_tehran_main_districts is not None: 
                gdf_pop_source = gdf_tehran_main_districts
                
            if gdf_pop_source is not None and 'Pop' in gdf_pop_source.columns:
                if selected_polygon_sub_types:
                    name_cols_poly = ['Name', 'NAME_MAHAL']
                    actual_name_col = next((col for col in name_cols_poly if col in gdf_pop_source.columns), None)
                    if actual_name_col: 
                        gdf_pop_source = gdf_pop_source[gdf_pop_source[actual_name_col].isin(selected_polygon_sub_types)]
                
                # Adjust point density based on zoom level for population heatmap
                base_divisor = 1000
                zoom_multiplier = max(0.1, min(2.0, (zoom_level / 11.0)))  # Scale with zoom
                point_density_divisor = base_divisor / zoom_multiplier
                
                temp_points = []
                for _, row in gdf_pop_source.iterrows():
                    population = safe_numeric_conversion(pd.Series([row['Pop']]), 0).iloc[0]
                    if population > 0:
                        num_points = int(population / point_density_divisor)
                        if num_points > 0:
                            generated_points = generate_random_points_in_polygon(row['geometry'], num_points)
                            for point in generated_points: 
                                temp_points.append({'lat': point.y, 'lng': point.x, 'value': 1})
                
                heatmap_data = temp_points
                print(f"Generated {len(heatmap_data)} points for population heatmap at zoom {zoom_level}")
        
        # --- Coverage Grid Generation ---
        if area_type_display == "coverage_grid":
            print(f"DEBUG: Generating coverage grid for {city_name}")
            
            vendor_codes_for_cache = sorted(df_v_filtered['vendor_code'].tolist()) if not df_v_filtered.empty and 'vendor_code' in df_v_filtered.columns else []
            cache_key = hashlib.md5(json.dumps({
                'city': city_name,
                'vendor_codes': vendor_codes_for_cache,
                'radius_modifier': radius_modifier, 'radius_mode': radius_mode, 'radius_fixed': radius_fixed,
                'business_lines': sorted(selected_business_lines)
            }, sort_keys=True).encode()).hexdigest()
            
            if cache_key in coverage_cache:
                print(f"DEBUG: Using cached coverage grid")
                coverage_grid_data = coverage_cache[cache_key]
            else:
                grid_points = generate_coverage_grid(city_name)
                point_area_info = find_marketing_area_for_points(grid_points, city_name)
                coverage_results = calculate_coverage_for_grid_vectorized(grid_points, df_v_filtered, city_name)
                
                use_target_based_logic = bool(
                    city_name == "tehran" and
                    len(selected_business_lines) == 1 and
                    target_lookup_dict
                )
                selected_bl_for_target = selected_business_lines[0] if use_target_based_logic else None
                
                print(f"DEBUG: Coverage logic check: Target-based = {use_target_based_logic}")
                if use_target_based_logic:
                    print(f"--- Analyzing for Business Line: '{selected_bl_for_target}'")
                
                temp_coverage_grid_data = []
                for i, coverage in enumerate(coverage_results):
                    if coverage['total_vendors'] > 0:
                        area_id, area_name = point_area_info[i]
                        point_data = {
                            'lat': coverage['lat'], 'lng': coverage['lng'],
                            'coverage': coverage, 'marketing_area': area_name
                        }
                        
                        if use_target_based_logic and area_id is not None:
                            target_key = (area_id, selected_bl_for_target)
                            target_value = target_lookup_dict.get(target_key)
                            
                            if i < 5:
                               print(f"--- Point {i}: area_id='{area_id}', bl='{selected_bl_for_target}'. Target lookup result: {target_value}")
                            if target_value is not None:
                                actual_value = coverage['by_business_line'].get(selected_bl_for_target, 0)
                                point_data['target_business_line'] = selected_bl_for_target
                                point_data['target_value'] = target_value
                                point_data['actual_value'] = actual_value
                                point_data['performance_ratio'] = (actual_value / target_value) if target_value > 0 else 2.0
                        temp_coverage_grid_data.append(point_data)
                
                coverage_grid_data = temp_coverage_grid_data
                
                if len(coverage_cache) > CACHE_SIZE: coverage_cache.clear()
                coverage_cache[cache_key] = coverage_grid_data
                print(f"Filtered to {len(coverage_grid_data)} coverage points with vendors")
        
        # --- Centralized Polygon Display & Enrichment Logic ---
        final_polygons_gdf = None
        if area_type_display != "none" and area_type_display != "coverage_grid":
            gdf_to_enrich, name_col_to_use = None, None
            if area_type_display == "tapsifood_marketing_areas" and city_name in gdf_marketing_areas:
                gdf_to_enrich, name_col_to_use = gdf_marketing_areas[city_name], 'name'
            elif city_name == "tehran":
                if area_type_display == "tehran_region_districts" and gdf_tehran_region is not None:
                    gdf_to_enrich, name_col_to_use = gdf_tehran_region, 'Name'
                elif area_type_display == "tehran_main_districts" and gdf_tehran_main_districts is not None:
                    gdf_to_enrich, name_col_to_use = gdf_tehran_main_districts, 'NAME_MAHAL'
            
            if gdf_to_enrich is not None and not gdf_to_enrich.empty and name_col_to_use is not None:
                final_polygons_gdf = enrich_polygons_with_stats(gdf_to_enrich, name_col_to_use, df_v_filtered, df_orders_filtered, df_orders_all_for_city)
            elif area_type_display == "all_tehran_districts" and city_name == 'tehran':
                enriched_list = []
                if gdf_tehran_region is not None: enriched_list.append(enrich_polygons_with_stats(gdf_tehran_region, 'Name', df_v_filtered, df_orders_filtered, df_orders_all_for_city))
                if gdf_tehran_main_districts is not None: enriched_list.append(enrich_polygons_with_stats(gdf_tehran_main_districts, 'NAME_MAHAL', df_v_filtered, df_orders_filtered, df_orders_all_for_city))
                if enriched_list: final_polygons_gdf = pd.concat(enriched_list, ignore_index=True)
            
            if final_polygons_gdf is not None and not final_polygons_gdf.empty:
                if selected_polygon_sub_types:
                    name_cols_poly = ['name', 'Name', 'NAME_MAHAL']
                    actual_name_col = next((col for col in name_cols_poly if col in final_polygons_gdf.columns), None)
                    if actual_name_col: final_polygons_gdf = final_polygons_gdf[final_polygons_gdf[actual_name_col].astype(str).isin(selected_polygon_sub_types)]
                if not final_polygons_gdf.empty:
                    clean_gdf = final_polygons_gdf.copy()
                    # FIX: Properly clean all columns
                    for col in clean_gdf.columns:
                        if col == 'geometry': continue
                        clean_gdf[col] = clean_gdf[col].astype(object).where(pd.notna(clean_gdf[col]), None)
                    polygons_geojson = clean_gdf.__geo_interface__
        
        # Marketing areas overlay for coverage grid
        if area_type_display == "coverage_grid" and city_name in gdf_marketing_areas:
            gdf_to_send = gdf_marketing_areas[city_name].copy()
            if selected_polygon_sub_types and 'name' in gdf_to_send.columns:
                gdf_to_send = gdf_to_send[gdf_to_send['name'].astype(str).isin(selected_polygon_sub_types)]
            if not gdf_to_send.empty:
                clean_gdf = gdf_to_send.copy()
                for col in clean_gdf.columns:
                    if col == 'geometry': continue
                    clean_gdf[col] = clean_gdf[col].astype(object).where(pd.notna(clean_gdf[col]), None)
                polygons_geojson = clean_gdf.__geo_interface__
        
        request_time = time.time() - request_start
        print(f"Request processed in {request_time:.2f}s")
        
        response_data = {
            "vendors": vendor_markers, 
            "heatmap_data": heatmap_data, 
            "polygons": polygons_geojson, 
            "coverage_grid": coverage_grid_data,
            "processing_time": request_time,
            # NEW: Add metadata for frontend optimization
            "zoom_level": zoom_level,
            "heatmap_type": heatmap_type_req
        }
        
        # FIX: Clean all data to ensure no NaN values in JSON
        response_data = clean_data_for_json(response_data)
        
        try:
            import ujson
            return app.response_class(ujson.dumps(response_data), mimetype='application/json')
        except ImportError:
            return jsonify(response_data)
            
    except Exception as e:
        import traceback
        print(f"Error in /api/map-data: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500
    
# --- Function to Open Browser ---
def open_browser():
    """Opens the web browser to the app's URL after a short delay."""
    time.sleep(1)
    webbrowser.open_new("http://127.0.0.1:5001/")

# --- Main Execution ---
if __name__ == '__main__':
    load_data()
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
         threading.Thread(target=open_browser).start()
    app.run(debug=True, port=5001, use_reloader=True)