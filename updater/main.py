import logging
import os
import threading

import aioredis
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv
from pymongo import MongoClient

from utils import fetch_and_store_ips, fetch_and_store_domains, fetch_and_store_urls

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

client = MongoClient(os.getenv('MONGO_DB'))
db = client[os.getenv('DB')]
collection = db[os.getenv('IP_COLLECTION')]
domain_collection = db[os.getenv('DOMAIN_COLLECTION')]
url_collection = db[os.getenv('URL_COLLECTION')]
meta_collection = db[os.getenv('META_COLLECTION')]
ip_url_collection = db[os.getenv('IP_URLS_COLLECTION')]
domain_url_collection = db[os.getenv('DOMAIN_URLS_COLLECTION')]
url_urls_collection = db[os.getenv('URL_URLS_COLLECTION')]
settings_collection = db[os.getenv('SETTINGS_COLLECTION')]

redis = aioredis.from_url("redis://localhost:8001")


async def reset_all_cache():
    await redis.flushdb()


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
    for entry in url_urls_collection.find():
        url_dict[entry["source"]] = entry["url"]
    return url_dict


def listen_for_updates():
    previous_ips = get_url_dict()
    previous_domains = get_domain_url_dict()
    previous_urls = get_url_url_dict()

    while True:
        current_ips = get_url_dict()
        current_domains = get_domain_url_dict()
        current_urls = get_url_url_dict()

        if previous_ips != current_ips:
            logging.info("IP list changed. Fetching and storing new IPs.")
            fetch_and_store_ips()
            reset_all_cache()
            previous_ips = current_ips

        if previous_domains != current_domains:
            logging.info("Domain list changed. Fetching and storing new domains.")
            fetch_and_store_domains()
            reset_all_cache()
            previous_domains = current_domains

        if previous_urls != current_urls:
            logging.info("URL list changed. Fetching and storing new URLs.")
            fetch_and_store_urls()
            reset_all_cache()
            previous_urls = current_urls


def listen_for_settings_updates():
    global update_interval
    global automatic_update
    global scheduler
    previous_interval = update_interval
    previous_automatic_update = automatic_update

    settings_document = settings_collection.find_one({"_id": 1})
    current_update_interval = settings_document["update_interval"] if settings_document else 1
    current_automatic_update = settings_document["enable_automatic_update"] if settings_document else True

    if previous_interval != current_update_interval:
        logging.info("Update interval changed. Updating scheduler.")
        update_interval = current_update_interval

        if scheduler.get_job("fetch_and_store_ips"):
            scheduler.remove_job(job_id="fetch_and_store_ips")
        if scheduler.get_job("fetch_and_store_domains"):
            scheduler.remove_job(job_id="fetch_and_store_domains")
        if scheduler.get_job("fetch_and_store_urls"):
            scheduler.remove_job(job_id="fetch_and_store_urls")
        if automatic_update:
            scheduler.add_job(fetch_and_store_ips, 'interval', hours=update_interval, id="fetch_and_store_ips")
            scheduler.add_job(fetch_and_store_domains, 'interval', hours=update_interval,
                              id="fetch_and_store_domains")
            scheduler.add_job(fetch_and_store_urls, 'interval', hours=update_interval, id="fetch_and_store_urls")

    if previous_automatic_update != current_automatic_update:
        logging.info("Automatic update setting changed. Updating scheduler.")
        automatic_update = current_automatic_update

        if scheduler.get_job("fetch_and_store_ips"):
            scheduler.remove_job(job_id="fetch_and_store_ips")
        if scheduler.get_job("fetch_and_store_domains"):
            scheduler.remove_job(job_id="fetch_and_store_domains")
        if scheduler.get_job("fetch_and_store_urls"):
            scheduler.remove_job(job_id="fetch_and_store_urls")
        if current_automatic_update:
            scheduler.add_job(fetch_and_store_ips, 'interval', hours=update_interval, id="fetch_and_store_ips")
            scheduler.add_job(fetch_and_store_domains, 'interval', hours=update_interval,
                              id="fetch_and_store_domains")
            scheduler.add_job(fetch_and_store_urls, 'interval', hours=update_interval, id="fetch_and_store_urls")


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


if __name__ == "__main__":
    scheduler = BlockingScheduler()
    fetch_and_store_ips()
    fetch_and_store_domains()
    fetch_and_store_urls()
    settings_doc = settings_collection.find_one({"_id": 1})
    update_interval = settings_doc["update_interval"] if settings_doc else 1
    automatic_update = settings_doc["enable_automatic_update"] if settings_doc else True

    threading.Thread(target=listen_for_updates, daemon=True).start()

    scheduler.add_job(listen_for_settings_updates, 'interval', seconds=10, id="listen_for_settings_updates")

    if automatic_update:
        scheduler.add_job(fetch_and_store_ips, 'interval', hours=update_interval, id="fetch_and_store_ips")
        scheduler.add_job(fetch_and_store_domains, 'interval', hours=update_interval, id="fetch_and_store_domains")
        scheduler.add_job(fetch_and_store_urls, 'interval', hours=update_interval, id="fetch_and_store_urls")

    scheduler.start()
