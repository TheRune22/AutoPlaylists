from dataclasses import dataclass
import requests
import base64
import json
import os
import socket
import re
from time import time, sleep
from functools import lru_cache


# TODO: split token and creds to separate files?
CRED_FILE = "creds.json"

SOCKET_NUM = 5002
REDIRECT_URI = f"http://localhost:{SOCKET_NUM}"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
AUTH_URL = "https://accounts.spotify.com/authorize"
NEW_AUTH = False


code_pattern = re.compile(r'^GET /\?code=([^ ]+)')


def get_authorization_code(creds):
    params = {
        "client_id": creds["client_id"],
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "show_dialog": "false",
        "scope":
            # "user-read-private "
            # "user-read-email "
            "user-library-read "
            "user-follow-read "
            "user-top-read "
            "user-read-recently-played "
            # "user-read-currently-playing "
            # "user-read-playback-state "
            # "user-read-playback-position "
            "playlist-read-private "
            "playlist-read-collaborative "
            "playlist-modify-public "
            "playlist-modify-private "
            # "user-follow-modify "
            # "user-library-modify"
            # "user-modify-playback-state "
            # "user-modify-playback-position "
            # "app-remote-control "
            # "streaming "
        ,
        # "state": "",
    }

    auth_response = requests.get(AUTH_URL, params=params)

    # TODO: avoid this?
    os.system(f"xdg-open {auth_response.url} > /dev/null 2>&1")

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("localhost", SOCKET_NUM))
    server_socket.listen(1)
    (client_socket, address) = server_socket.accept()

    http_req = client_socket.recv(1024)

    # print(response.decode())

    client_socket.send(b"HTTP/1.1 200 OK\r\nContent-type: text/html\r\n\r\n <script>close()</script>\r\n\r\n")

    client_socket.shutdown(socket.SHUT_RDWR)
    client_socket.close()
    server_socket.shutdown(socket.SHUT_RDWR)
    server_socket.close()

    # TODO: error handling
    code = code_pattern.findall(http_req.decode())[0]

    return code


def get_access_token(creds, auth_code):
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
    }

    auth_response = requests.post(TOKEN_URL, data=data, auth=(creds["client_id"], creds["client_secret"]))

    return auth_response.json()


def refresh_access_token(creds):
    data = {
        "grant_type": "refresh_token",
        "refresh_token": creds["refresh_token"],
    }

    auth_response = requests.post(TOKEN_URL, data=data, auth=(creds["client_id"], creds["client_secret"]))

    return auth_response.json()


def get_or_refresh_access_token():
    if os.path.exists(CRED_FILE):
        with open(CRED_FILE, "r") as f:
            creds = json.load(f)

            if NEW_AUTH:
                auth_code = get_authorization_code(creds)
                access_response = get_access_token(creds, auth_code)
                creds["access_token"] = access_response["access_token"]
                creds["refresh_token"] = access_response["refresh_token"]
                creds["expiry_time"] = time() + access_response["expires_in"]
            elif creds["expiry_time"] > time():
                return creds["access_token"]
            else:
                refresh_response = refresh_access_token(creds)
                creds["access_token"] = refresh_response["access_token"]
                creds["expiry_time"] = time() + refresh_response["expires_in"]
    else:
        creds = {"client_id": input("client_id: "), "client_secret": input("client_secret: ")}
        auth_code = get_authorization_code(creds)
        access_response = get_access_token(creds, auth_code)
        creds["access_token"] = access_response["access_token"]
        creds["refresh_token"] = access_response["refresh_token"]
        creds["expiry_time"] = time() + access_response["expires_in"]
    with open(CRED_FILE, "w") as f:
        json.dump(creds, f)
    return creds["access_token"]


access_token = get_or_refresh_access_token()
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
}

#%%


# TODO: fix size, custom cache, save to file, don't save playlists, only save artists?, refresh access token,
@lru_cache(maxsize=None)
def get_api_response(url):
    if url.startswith("/"):
        url = API_URL + url

    response = requests.get(url, headers=headers)

    while response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            retry_after = int(retry_after)
            print(f"API rate limit exceeded, retrying in {retry_after} seconds")
            sleep(retry_after)
        else:
            print("API rate limit exceeded, retrying in 5 seconds")
            sleep(5)

        response = requests.get(url, headers=headers)


    return response.json()


def get_items(url):
    # TODO: use max elements
    items = []
    url += "?limit=50"
    while url:
        response = get_api_response(url)
        items += response["items"]
        url = response["next"]
    return items


def get_track_uris(url):
    return [track["track"]["uri"] for track in get_items(url)]


def add_to_playlist(href, uris):
    for i in range(0, len(uris), 100):
        response = requests.post(href, headers=headers, json={"uris": uris[i:i + 100]})

        while response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                retry_after = int(retry_after)
                print(f"API rate limit exceeded, retrying in {retry_after} seconds")
                sleep(retry_after)
            else:
                print("API rate limit exceeded, retrying in 5 seconds")
                sleep(5)

            response = requests.post(href, headers=headers, json={"uris": uris[i:i + 100]})


#%%


@dataclass
class Union:
    Playlists: list[str]
    Url: str


@dataclass
class Intersection:
    Playlists: list[str]
    Url: str


@dataclass
class Difference:
    Playlist1: str
    Playlist2: str
    Url: str


@dataclass
class Artists:
    Artists: list[str]
    Url: str


@dataclass
class Genres:
    Genres: list[str]
    Url: str


# TODO: use grammar instead?
union_pattern = re.compile(r'.*?_UNION_:(.*)')
intersection_pattern = re.compile(r'.*?_INTERSECTION_:(.*)')
artists_pattern = re.compile(r'.*?_ARTISTS_:(.*)')
genres_pattern = re.compile(r'.*?_GENRES_:(.*)')

playlists_pattern = re.compile(r'"([^"]+)"')
items_pattern = re.compile(r'([^;]+)')


def parse_auto_playlist_name(name: str, url: str):
    # TODO: make more general

    union_match = union_pattern.match(name)
    if union_match:
        return Union(playlists_pattern.findall(union_match.group(1)), url)

    intersection_match = intersection_pattern.match(name)
    if intersection_match:
        return Intersection(playlists_pattern.findall(intersection_match.group(1)), url)

    artists_match = artists_pattern.match(name)
    if artists_match:
        return Artists(items_pattern.findall(artists_match.group(1)), url)

    genres_match = genres_pattern.match(name)
    if genres_match:
        return Genres(items_pattern.findall(genres_match.group(1)), url)

    else:
        return None


def fill_auto_playlists():
    playlist_tracks = {"_LIKED_": "/me/tracks"}
    auto_playlists = []

    liked_tracks = get_items("/me/tracks")

    for item in get_items("/me/playlists"):
        # TODO: preload all playlists?
        # playlist_tracks.update({item["name"]: get_items(item["tracks"]["href"])})
        playlist_tracks.update({item["name"]: item["tracks"]["href"]})

        auto_playlist = parse_auto_playlist_name(item["name"], item["tracks"]["href"])
        if auto_playlist:
            auto_playlists.append(auto_playlist)

    for auto_playlist in auto_playlists:
        match auto_playlist:
            case Union(playlists, auto_playlist_tracks_url):
                existing_tracks = set(get_track_uris(auto_playlist_tracks_url))
                new_tracks = []

                for playlist in playlists:
                    new_tracks += get_track_uris(playlist_tracks[playlist])

                new_tracks = list(set(new_tracks) - existing_tracks)
                if new_tracks:
                    add_to_playlist(auto_playlist_tracks_url, new_tracks)

            case Intersection(playlists, auto_playlist_tracks_url):
                existing_tracks = set(get_track_uris(auto_playlist_tracks_url))
                new_tracks = set(get_track_uris(playlist_tracks[playlists[0]]))

                for playlist in playlists[1:]:
                    new_tracks = new_tracks.intersection(get_track_uris(playlist_tracks[playlist]))

                new_tracks = list(new_tracks - existing_tracks)
                if new_tracks:
                    add_to_playlist(auto_playlist_tracks_url, new_tracks)

            case Artists(artists, auto_playlist_tracks_url):
                existing_tracks = set(get_track_uris(auto_playlist_tracks_url))
                new_tracks = []

                for track in liked_tracks:
                    # TODO: check all artists and features
                    if track["track"]["artists"][0]["name"] in artists:
                        new_tracks.append(track["track"]["uri"])

                new_tracks = list(set(new_tracks) - existing_tracks)
                add_to_playlist(auto_playlist_tracks_url, new_tracks)

            case Genres(genres, auto_playlist_tracks_url):
                existing_tracks = set(get_track_uris(auto_playlist_tracks_url))
                new_tracks = []

                for track in liked_tracks:
                    # TODO: check all artists and features?
                    # print(get_api_response(track["track"]["artists"][0]["href"]))
                    for genre in get_api_response(track["track"]["artists"][0]["href"])["genres"]:
                        if genre in genres:
                            new_tracks.append(track["track"]["uri"])
                            break

                new_tracks = list(set(new_tracks) - existing_tracks)
                add_to_playlist(auto_playlist_tracks_url, new_tracks)

    print("done")


fill_auto_playlists()


# Implemented playlist types:
# _UNION_:"Test 1";"Test 2";"Test 3"
# _ARTISTS_:Kendrick Lamar;Kanye West
# _GENRES_:rap;hip hop
# TODO:
# intersection
# difference
# more general (json?) query
# combinations of above


# TODO: move auto code to end?
# TODO: get available genres
# TODO: don't overwrite manual edits
