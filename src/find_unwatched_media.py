#!/usr/bin/env python3

import os
import re
import json
import argparse
import requests
from datetime import datetime


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
        self._grab_content_library()

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
        # Pass 1 for movies and 2 for TV shows
        movie_section_id = 1
        tv_show_section_id = 2

        # Fetch movie media info from Tautulli
        movie_data = self.get_tautulli_data(movie_section_id)["data"]["data"]
        # Fetch TV show media info from Tautulli
        tv_show_data = self.get_tautulli_data(tv_show_section_id)["data"]["data"]
        all_media_data = movie_data + tv_show_data

        for media in all_media_data:
            if media['last_played'] is None or int(media['last_played']) == 0:
                arr_info = self.get_arr_info(media["rating_key"])
                if not arr_info:
                    continue
                if "(Do Not Delete)" not in arr_info["path"]:
                    self.unwatched_media.append(
                        {'title': media['title'], 'path': arr_info["path"]})

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
            return None
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
                    return media

        if fuzzy_title_match:
            print(f"Fuzzy title search match for: {tautulli_media_metadata["title"]}")
        else:
            print(f"No match found for: {tautulli_media_metadata["title"]}")
            return None

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

    @staticmethod
    def clean_title(title):
        # Remove years and punctuation
        cleaned_title = re.sub(r'\b\d{4}\b|[^\w\s]', '', title)
        return cleaned_title.strip()


if __name__ == '__main__':
    watch_checker = WatchStatusChecker()
    watch_checker.get_unwatched_media()
    watch_checker.notify_discrepancies()
