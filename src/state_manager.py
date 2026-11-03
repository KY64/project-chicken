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


def save_new_urls(csv_path: str, new_urls: List[str]) -> int:
    """
    Append URLs that are not in the CSV yet and return how many were written.

    This file is the only record of what has been published, so an URL must
    never land in it twice: duplicates cannot cause a wrong filter decision
    (load_seen_urls builds a set) but they hide real divergence between the
    feed branches and state, and they make the file misleading to inspect.

    Callers must have main checked out. On a site's orphan branch the state
    file is not tracked, and a write there disappears when the run switches
    back to main.

    Args:
        csv_path: Path to the CSV file
        new_urls: URLs of articles published in this run

    Returns:
        Number of URLs actually appended (0 when everything was already known)
    """
    seen_urls = load_seen_urls(csv_path)
    to_write = []
    for url in new_urls:
        # Guard within the batch too: a caller may pass a repeated URL.
        if url not in seen_urls:
            seen_urls.add(url)
            to_write.append(url)

    if not to_write:
        return 0

    # Create directory if it doesn't exist
    csv_dir = os.path.dirname(csv_path) or '.'
    os.makedirs(csv_dir, exist_ok=True)

    # Append mode - create file if it doesn't exist
    with open(csv_path, 'a', newline='') as f:
        writer = csv.writer(f)
        for url in to_write:
            writer.writerow([url])

    return len(to_write)
