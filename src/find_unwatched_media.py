#!/usr/bin/env python3

import os
import re
import json
import argparse
import requests
from datetime import datetime, timedelta


class WatchStatusChecker:
    def __init__(self):
        with open(f"{os.path.dirname(os.path.abspath(__file__))}/config.json") as f:
            config = json.load(f)

        parser = argparse.ArgumentParser()
        parser.add_argument("--tautulli-host", default=config["tautulli_host"],
                            help="Tautulli API URL")
        parser.add_argument("--tautulli-token", default=config["tautulli_token"],
                            help="Tautulli API Key")
        parser.add_argument("--sonarr-host", default=config["sonarr_host"],
                            help="Hostname or IP address of your Sonarr server")
        parser.add_argument("--sonarr-token", default=config["sonarr_token"],
                            help="Sonarr API token")
        parser.add_argument("--radarr-host", default=config["radarr_host"],
                            help="Hostname or IP address of your Radarr server")
        parser.add_argument("--radarr-token", default=config["radarr_token"],
                            help="Radarr API token")
        self.docker = config["DOCKER"]
        self.args = parser.parse_args()

        self.print_timestamp_if_docker()
        print("Starting Check")

        if not self.args.tautulli_host or not self.args.tautulli_token \
                or not self.args.sonarr_host or not self.args.sonarr_token \
                or not self.args.radarr_host or not self.args.radarr_token:
            print("The following arguments are required: "
                  "tautulli-host, tautulli-token, sonarr-host, sonarr-token, radarr-host, radarr-token")
            exit(1)

        self.tautulli_headers = {'apikey': self.args.tautulli_host}
        self.unwatched_media = []

    def print_timestamp_if_docker(self):
        if self.docker:
            print(f"{datetime.now()}: ", end="")

    def get_tautulli_data(self, section_id):
        # Fetch media info from Tautulli library
        params = {
            'apikey': self.args.tautulli_token,
            'cmd': 'get_library_media_info',
            'section_id': section_id,
            'length': 5000  # Adjust this to the maximum number of items you want to retrieve
        }
        response = requests.get(f"{self.args.tautulli_host}/api/v2", params=params)
        return response.json()["response"]

    def get_unwatched_media(self):
        self._grab_content_library()

        # Pass 1 for movies and 2 for TV shows
        movie_section_id = 1
        tv_show_section_id = 2

        # Fetch movie media info from Tautulli
        movie_data = self.get_tautulli_data(movie_section_id)["data"]["data"]
        # Fetch TV show media info from Tautulli
        tv_show_data = self.get_tautulli_data(tv_show_section_id)["data"]["data"]
        all_media_data = movie_data + tv_show_data

        two_months_ago = datetime.now() - timedelta(days=60)  # Assuming 2 months = 60 days
        all_media_data = [item for item in all_media_data if datetime.fromtimestamp(int(item['added_at'])) <= two_months_ago]

        for media in all_media_data:
            if media['last_played'] is None or int(media['last_played']) == 0:
                arr_info, media_type = self.get_arr_info(media["rating_key"])
                if not arr_info:
                    continue
                if "(Do Not Delete)" not in arr_info["path"]:
                    if media_type == "show":
                        url = f"{self.args.sonarr_host}/series/{arr_info["titleSlug"]}"
                    else:
                        url = f"{self.args.radarr_host}/movie/{arr_info["titleSlug"]}"
                    self.unwatched_media.append(
                        {"title": media["title"], "path": arr_info["path"],
                         "id": arr_info["id"], "type": media_type, "url": url, "year": arr_info["year"]})

    def get_arr_info(self, tautulli_rating_key):
        params = {
            'apikey': self.args.tautulli_token,
            'cmd': 'get_metadata',
            'rating_key': tautulli_rating_key
        }
        tautulli_media_metadata = requests.get(f"{self.args.tautulli_host}/api/v2", params=params).json()
        tautulli_media_metadata = tautulli_media_metadata["response"]["data"]
        if not tautulli_media_metadata:
            print(f"No item found for rating key: {tautulli_rating_key}")
            return None, None
        guids_ids = [guid.split('//')[1] for guid in tautulli_media_metadata["guids"]]

        if tautulli_media_metadata["media_type"] == "show":
            library = self._tv_library
        elif tautulli_media_metadata["media_type"] == "movie":
            library = self._movie_library
        else:
            print(f"Invalid media type: {tautulli_media_metadata["media_type"]}")
            exit(1)

        fuzzy_title_match = None
        for media in library:
            if self.clean_title(media["title"]) == self.clean_title(tautulli_media_metadata["title"]):
                fuzzy_title_match = media
            for key in ["imdbId", "tmdbId", "tvdbId"]:
                if media.get(key) in guids_ids:
                    return media, tautulli_media_metadata["media_type"]

        if fuzzy_title_match:
            print(f"Fuzzy title search match for: {tautulli_media_metadata["title"]}")
            return fuzzy_title_match, tautulli_media_metadata["media_type"]
        else:
            print(f"No match found for: {tautulli_media_metadata["title"]}")
            return None, None

    def _grab_content_library(self):
        series_request = f"{self.args.sonarr_host}/api/v3/series/?apikey={self.args.sonarr_token}"
        self._tv_library = json.loads(requests.get(series_request).text)
        movies_request = f"{self.args.radarr_host}/api/v3/movie/?apikey={self.args.radarr_token}"
        self._movie_library = json.loads(requests.get(movies_request).text)

    def notify_discrepancies(self):
        if self.unwatched_media:
            self.print_timestamp_if_docker()
            print("Discrepancies found.\n"
                  f"\tMovies: {self.unwatched_media}")
        else:
            self.print_timestamp_if_docker()
            print("No discrepancies found :)")
        self.print_timestamp_if_docker()
        print("Done!\n")

    def delete_media(self):
        counter = 1
        for media in self.unwatched_media:
            if input(f"({counter}/{len(self.unwatched_media)}) {media["title"]} {media["year"]}: {media["url"]} (y/n) - ").lower() == "y":
                if media["type"] == "show":
                    delete_url = f"{self.args.sonarr_host}/api/v3/series/{media["id"]}?apikey={self.args.sonarr_token}&deleteFiles=true"
                else:
                    delete_url = f"{self.args.radarr_host}/api/v3/movie/{media["id"]}?apikey={self.args.radarr_token}&deleteFiles=true"
                response = requests.delete(delete_url)
                if response.status_code == 200:
                    print(f"Deleted {media["title"]}")
                else:
                    print(f"Failed to delete {media["title"]}")
            counter += 1

    @staticmethod
    def clean_title(title):
        # Remove years and punctuation
        cleaned_title = re.sub(r'\b\d{4}\b|[^\w\s]', '', title)
        return cleaned_title.strip()


if __name__ == '__main__':
    watch_checker = WatchStatusChecker()
    if not os.path.exists("unwatched_media.json") or input(f"Skip refresh? (y/n) ").lower() == "n":
        watch_checker.get_unwatched_media()
        watch_checker.notify_discrepancies()
        with open('unwatched_media.json', 'w') as f:
            json.dump(watch_checker.unwatched_media, f)
    with open('unwatched_media.json') as f:
        watch_checker.unwatched_media = json.load(f)
    watch_checker.delete_media()
