import threading
import logging
from datetime import datetime
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from pymongo import MongoClient, ASCENDING
from pymongo.errors import ServerSelectionTimeoutError, OperationFailure
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

client = MongoClient("mongodb://host.docker.internal:27017/")
db = client["checker"]
collection = db["ip_addresses"]
domain_collection = db["domains"]
url_collection = db["urls"]
meta_collection = db["metadata"]
ip_url_collection = db["ip_urls"]
domain_url_collection = db["domain_urls"]
url_url_collection = db["url_urls"]

# collection.create_index([("ip", ASCENDING)], unique=True)
# domain_collection.create_index([("domain", ASCENDING)], unique=True)
# url_collection.create_index([("url", ASCENDING)], unique=True)

def get_url_dict():
    url_dict = {}
    for entry in ip_url_collection.find():
        if entry["source"] != "trigger":
            url_dict[entry["source"]] = entry["url"]
    return url_dict

def get_domain_url_dict():
    url_dict = {}
    for entry in domain_url_collection.find():
        url_dict[entry["source"]] = entry["url"]
    return url_dict

def get_url_url_dict():
    url_dict = {}
    for entry in url_url_collection.find():
        url_dict[entry["source"]] = entry["url"]
    return url_dict

def read_local_file(file_path):
    try:
        with open(file_path, 'r') as file:
            return file.read().splitlines()
    except Exception as e:
        logging.error(f"Failed to read local file {file_path}: {e}")
        return []

def fetch_and_store_ips():
    last_updated = datetime.utcnow()
    new_ips = []
    seen_ips = set()
    url_dict = get_url_dict()

    for label, url in url_dict.items():
        try:
            if 'localhost' in url or '127.0.0.1' in url or '156.67.80.79' in url:
                file_path = url.replace('http://localhost:8000', '').replace('http://127.0.0.1:8000', '').replace('http://156.67.80.79:8000', '')
                if file_path.startswith('/'):
                    file_path = file_path[1:]
                ip_list = read_local_file(file_path)
            else:
                response = requests.get(url)
                response.raise_for_status()
                ip_list = response.text.splitlines()

            for ip in ip_list:
                if ip not in seen_ips:
                    new_ips.append({"ip": ip, "source": label})
                    seen_ips.add(ip)
        except requests.RequestException as e:
            logging.error(f"Failed to fetch IPs from {url}: {e}")

    if new_ips:
        collection.delete_many({})
        collection.insert_many(new_ips)
        meta_collection.update_one(
            {"_id": "last_updated"},
            {"$set": {"timestamp": last_updated}},
            upsert=True
        )
        logging.info(f"IP addresses updated at {last_updated}")
        # cleanup_duplicates()

def fetch_and_store_domains():
    last_updated = datetime.utcnow()
    new_domains = []
    seen_domains = set()
    url_dict = get_domain_url_dict()

    for label, url in url_dict.items():
        try:
            if 'localhost' in url or '127.0.0.1' in url or '156.67.80.79' in url:
                file_path = url.replace('http://localhost:8000', '').replace('http://127.0.0.1:8000', '').replace('http://156.67.80.79:8000', '')
                if file_path.startswith('/'):
                    file_path = file_path[1:]
                domain_list = read_local_file(file_path)
            else:
                response = requests.get(url)
                response.raise_for_status()
                domain_list = response.text.splitlines()

            for domain in domain_list:
                if domain not in seen_domains:
                    new_domains.append({"domain": domain, "source": label})
                    seen_domains.add(domain)
        except requests.RequestException as e:
            logging.error(f"Failed to fetch domains from {url}: {e}")

    if new_domains:
        domain_collection.delete_many({})
        domain_collection.insert_many(new_domains)
        meta_collection.update_one(
            {"_id": "last_updated"},
            {"$set": {"timestamp": last_updated}},
            upsert=True
        )
        logging.info(f"Domains updated at {last_updated}")
        # cleanup_duplicate_domains()

def fetch_and_store_urls():
    last_updated = datetime.utcnow()
    new_urls = []
    seen_urls = set()
    url_dict = get_url_url_dict()

    for label, url in url_dict.items():
        try:
            if 'localhost' in url or '127.0.0.1' in url or '156.67.80.79' in url:
                file_path = url.replace('http://localhost:8000', '').replace('http://127.0.0.1:8000', '').replace('http://156.67.80.79:8000', '')
                if file_path.startswith('/'):
                    file_path = file_path[1:]
                url_list = read_local_file(file_path)
            else:
                response = requests.get(url)
                response.raise_for_status()
                url_list = response.text.splitlines()

            for url1 in url_list:
                if url1 not in seen_urls:
                    new_urls.append({"url": url1, "source": label})
                    seen_urls.add(url1)
        except requests.RequestException as e:
            logging.error(f"Failed to fetch URLs from {url}: {e}")

    if new_urls:
        url_collection.delete_many({})
        url_collection.insert_many(new_urls)
        meta_collection.update_one(
            {"_id": "last_updated"},
            {"$set": {"timestamp": last_updated}},
            upsert=True
        )
        logging.info(f"URLs updated at {last_updated}")
        # cleanup_duplicate_urls()

def listen_for_updates():
    previous_ips = get_url_dict()
    previous_domains = get_domain_url_dict()
    previous_urls = get_url_url_dict()

    while True:
        current_ips = get_url_dict()
        current_domains = get_domain_url_dict()
        current_urls = get_url_url_dict()

        if previous_ips != current_ips:
            fetch_and_store_ips()
            previous_ips = current_ips

        if previous_domains != current_domains:
            fetch_and_store_domains()
            previous_domains = current_domains

        if previous_urls != current_urls:
            fetch_and_store_urls()
            previous_urls = current_urls

def cleanup_duplicates():
    pipeline = [
        {"$group": {
            "_id": "$ip",
            "count": {"$sum": 1},
            "docs": {"$push": "$$ROOT"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]

    duplicates = list(collection.aggregate(pipeline))

    for duplicate in duplicates:
        docs_to_remove = duplicate["docs"][1:]
        ids_to_remove = [doc["_id"] for doc in docs_to_remove]
        collection.delete_many({"_id": {"$in": ids_to_remove}})
        logging.info(f"Removed {len(ids_to_remove)} duplicate(s) for IP {duplicate['_id']}")

def cleanup_duplicate_domains():
    pipeline = [
        {"$group": {
            "_id": "$domain",
            "count": {"$sum": 1},
            "docs": {"$push": "$$ROOT"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]

    duplicates = list(domain_collection.aggregate(pipeline))

    for duplicate in duplicates:
        docs_to_remove = duplicate["docs"][1:]
        ids_to_remove = [doc["_id"] for doc in docs_to_remove]
        domain_collection.delete_many({"_id": {"$in": ids_to_remove}})
        logging.info(f"Removed {len(ids_to_remove)} duplicate(s) for domain {duplicate['_id']}")

def cleanup_duplicate_urls():
    pipeline = [
        {"$group": {
            "_id": "$url",
            "count": {"$sum": 1},
            "docs": {"$push": "$$ROOT"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]

    duplicates = list(url_collection.aggregate(pipeline))

    for duplicate in duplicates:
        docs_to_remove = duplicate["docs"][1:]
        ids_to_remove = [doc["_id"] for doc in docs_to_remove]
        url_collection.delete_many({"_id": {"$in": ids_to_remove}})
        logging.info(f"Removed {len(ids_to_remove)} duplicate(s) for URL {duplicate['_id']}")

scheduler = BlockingScheduler()
scheduler.add_job(fetch_and_store_ips, 'interval', hours=2)
scheduler.add_job(fetch_and_store_domains, 'interval', hours=2)
scheduler.add_job(fetch_and_store_urls, 'interval', hours=2)
# scheduler.add_job(listen_for_updates, 'interval', minutes=1)

def ensure_replica_set_initiated():
    global sync_client
    try:
        sync_client = MongoClient("mongodb://host.docker.internal:27017/")
        # Attempt to check the replica set status
        rs_status = client.admin.command("replSetGetStatus")
        logging.info("Replica set already initiated")
    except OperationFailure as e:
        if e.details.get('code') == 94:
            logging.info("Initiating replica set")
            sync_client.admin.command("replSetInitiate")
        else:
            raise e
    except ServerSelectionTimeoutError:
        logging.error("Could not connect to MongoDB server. Ensure MongoDB is running.")

if __name__ == "__main__":
    # ensure_replica_set_initiated()
    threading.Thread(target=listen_for_updates, daemon=True).start()
    fetch_and_store_ips()
    fetch_and_store_domains()
    fetch_and_store_urls()
    scheduler.start()
