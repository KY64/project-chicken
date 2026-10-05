import csv
import os
from typing import Set, List


def load_seen_urls(csv_path: str) -> Set[str]:
    """
    Load seen URLs from a CSV file into a set.
    
    Args:
        csv_path: Path to the CSV file
        
    Returns:
        Set of URLs that have been seen
    """
    if not os.path.exists(csv_path):
        return set()
    
    seen_urls = set()
    with open(csv_path, 'r', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue  # Skip empty rows
            seen_urls.add(row[0])
    
    return seen_urls


def save_new_urls(csv_path: str, new_urls: List[str]) -> None:
    """
    Append new URLs to a CSV file.
    
    Args:
        csv_path: Path to the CSV file
        new_urls: List of new URLs to append
    """
    # Create directory if it doesn't exist
    csv_dir = os.path.dirname(csv_path) or '.'
    os.makedirs(csv_dir, exist_ok=True)
    
    # Append mode - create file if it doesn't exist
    with open(csv_path, 'a', newline='') as f:
        writer = csv.writer(f)
        for url in new_urls:
            writer.writerow([url])
