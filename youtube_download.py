from picard.album import Album
from picard.ui.itemviews import BaseAction, register_album_action
from ytmusicapi import YTMusic
import requests
import time
import tempfile
import os
from typing import Optional, Union, Dict, Any, List

PLUGIN_NAME = "Download Songs from Youtube."
PLUGIN_AUTHOR = "lumine"
PLUGIN_DESCRIPTION = (
    "Adds a context menu shortcut to download missing tracks from an album."
)
PLUGIN_VERSION = "0.1"
PLUGIN_API_VERSIONS = ["2.1", "2.2"]
PLUGIN_LICENSE = "GPL-3.0-or-later"
PLUGIN_LICENSE_URL = "https://www.gnu.org/licenses/gpl.txt"


BASE_URL = "https://music.yt2api.com/api/json"
TASK_URL = f"{BASE_URL}/task"
BITRATE_192 = 192

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": "https://ytapi.cc/",
}


def post_call(
    data: Dict[str, Any], is_task: bool = False
) -> Union[Dict[str, Any], None]:
    """Make a POST request to the music.yt2api.com API.

    Args:
        data (Dict[str, Any]): The JSON data to be sent in the request body.
        is_task (bool, optional): If True, the request will be sent to
            the task endpoint. Defaults to False.

    Returns:
        Union[Dict[str, Any], None]: The JSON response data if the request is successful,
            None if the request fails.
    """
    url = TASK_URL if is_task else BASE_URL
    response = requests.post(url, headers=HEADERS, json=data)

    # Check the response
    if response.ok:
        return response.json()
    else:
        response.raise_for_status()  # Raise an exception if the request failed


def search_video(video_url: str) -> Optional[Dict[str, Any]]:
    """Search for a video and return the response containing tasks."""
    data = {"ftype": "mp3", "url": video_url}
    response = post_call(data=data)
    return response


def create_conversion_task(tasks: Dict[str, Any], bitrate: int) -> Optional[str]:
    """Create a conversion task and return the task ID."""
    for task in tasks.get("tasks", []):
        if task.get("bitrate") == bitrate:
            data = {"hash": task.get("hash")}
            response = post_call(data=data)
            return response.get("taskId")
    return None


def wait_for_conversion_completion(task_id: str, max_retries: int = 10) -> bool:
    """Wait for conversion to be completed and return True if successful, False otherwise."""
    data = {"taskId": task_id}
    for _ in range(max_retries + 1):
        convert_results = post_call(data=data, is_task=True)
        if convert_results.get("status") == "finished":
            return True
        print("Waiting...")
        time.sleep(1)
    return False


def download_mp3(download_url: str, filename: str) -> bool:
    """Download the MP3 file from the given URL and save it with the specified filename."""
    response = requests.get(download_url)
    if response.status_code == 200:
        with open(filename, "wb") as f:
            f.write(response.content)
        return True
    else:
        print("Download failed with status code:", response.status_code)
        return False


def download_link(video_url: str, filename: str, max_retries: int = 10) -> bool:
    """Download a video from a given URL and convert it to an MP3 file with a bitrate of 192 kbps.

    Args:
        video_url (str): The URL of the video to be downloaded.
        filename (str): The name of the file to be saved.
        max_retries (int, optional): The maximum number of retries for conversion status checking.
            Defaults to 10.

    Returns:
        bool: True if the download and conversion were successful, False otherwise.
    """
    print(f"Search for video {video_url}.")
    tasks_response = search_video(video_url)

    task_id = create_conversion_task(tasks_response, bitrate=BITRATE_192)
    if not task_id:
        print("No suitable task found for conversion.")
        return False

    print("Wait for conversion.")
    if not wait_for_conversion_completion(task_id, max_retries):
        print("Conversion not completed within the specified time.")
        return False

    print("Downloading.")
    download_results = post_call(data={"taskId": task_id}, is_task=True)
    download_url = download_results.get("download")
    if not download_url:
        print("Download URL not found in the response.")
        return False

    return download_mp3(download_url, filename)


def search_and_download(query: str, filename: str) -> Optional[bool]:
    """Search for a song using the YTMusic API and download it as an MP3 file.

    Args:
        query (str): The search query for the song.
        filename (str): The name of the file to be saved.

    Returns:
        Optional[bool]: True if the download was successful, False if the song is not found, None if an error occurs.
    """
    try:
        ytmusic = YTMusic()
        search_results = ytmusic.search(query, filter="songs")
    except Exception as e:
        print("Error occurred during the search:", str(e))
        return False

    if not search_results:
        print("Song not found.")
        return False

    first_result = search_results[0]

    video_id = first_result.get("videoId")
    if not video_id:
        print("Video ID not found in the search results.")
        return None

    print("-------------")
    print(f"Title:   {first_result['title']}")
    print(f"Album:   {first_result['album']['name']}")
    print(f"Origin:  https://music.youtube.com/watch?v={first_result['videoId']}")
    print(f"Save To: {filename}")
    print("-------------")

    video_url = f"https://music.youtube.com/watch?v={video_id}"
    return download_link(video_url=video_url, filename=filename)


class DownloadSong(BaseAction):
    NAME = "Download songs..."

    def download_track(self, artists: List[str], title: str, filename: str) -> bool:
        """Download a song and return True if successful, False otherwise."""
        query = f"{' '.join(artists)} {title}"

        print(f"Downloading {title}...")
        success = search_and_download(query=query, filename=filename)
        if success:
            print(f"Downloaded {title} successfully.")
        else:
            print(f"Failed to download {title}.")
        return success

    def process_album(self, album: Album) -> None:
        """Process an album and download missing songs."""
        if not isinstance(album, Album):
            return

        temp_dir = tempfile.mkdtemp()
        for track in album.tracks:
            if "artists" in track.metadata:
                artists = track.metadata.getall("artists")
            elif "artist" in track.metadata:
                artists = track.metadata.getall("artist")
            else:
                continue

            if len(track.files) == 0:
                title = " ".join(track.metadata.getall("title"))
                filename = os.path.join(temp_dir, f"{title}.mp3")
                self.download_track(artists, title, filename)
                track.tagger.add_files([filename])

    def callback(self, objs):
        """Process a list of albums and download missing songs."""
        for album in objs:
            self.process_album(album)


register_album_action(DownloadSong())
