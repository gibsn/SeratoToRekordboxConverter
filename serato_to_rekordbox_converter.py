# Serato to Rekordbox converter by BytePhoenix
# TODO: print number of tracks failed and successfully converted


import argparse
import base64
import os
import re
import struct
import sys
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

PATH_LENGTH_OFFSET = 4
START_MARKER = b'ptrk'
START_MARKER_FULL_LENGTH = len(START_MARKER) + PATH_LENGTH_OFFSET
MEMORY_CUE_ID = -1
SERATO_DATABASE_FILE_NAME = "database V2"

DEFAULT_SERATO_FOLDER_PATH = "~/Music/_Serato_"
DEFAULT_VOLUME_WITH_TRACKS = "/"
DEFAULT_COPY_TO_MEMORY_CUES = True
DEFAULT_OUTPUT_FILE_NAME = "Serato_Converted.xml"


class TrackKey:
    NOTATION_CAMELOT     = 0
    NOTATION_TRADITIONAL = 1

    _traditional_to_camelot_map = {
        "b":  "1B",              "abm": "1A",  "g#m": "1A",
        "f#": "2B",  "gb": "2B", "ebm": "2A",  "d#m": "2A",
        "db": "3B",  "c#": "3B", "bbm": "3A",  "a#m": "3A",
        "ab": "4B",  "g#": "4B", "fm":  "4A",
        "eb": "5B",  "d#": "5B", "cm":  "5A",
        "bb": "6B",  "a#": "6B", "gm":  "6A",
        "f":  "7B",              "dm":  "7A",
        "c":  "8B",              "am":  "8A",
        "g":  "9B",              "em":  "9A",
        "d":  "10B",             "bm":  "10A",
        "a":  "11B",             "f#m": "11A", "gbm": "11A",
        "e":  "12B",             "dbm": "12A", "c#m": "12A",
    }

    _key: str  # as provided on initialisation, but cleaned
    _notation_type: int

    # constructor converts the given key to a standartised notation
    def __init__(self, key: str):
        key = key.lower()

        if len(key) > 0 and key[0].isdigit():
            self._notation_type = TrackKey.NOTATION_CAMELOT
            self._key = key
            return

        self._notation_type = TrackKey.NOTATION_TRADITIONAL

        if key.endswith("maj"):
            key = key[:-3]
        elif key.endswith("min"):
            key = key[:-2]

        self._key = key

    @staticmethod
    def _camelot_to_traditional(key: str) -> str:
        # TODO
        raise Exception("camelot to traditional convertion is not implemented")

    @staticmethod
    def _traditional_to_camelot(key: str) -> str:
        if len(key) == 0:
            return ""

        return TrackKey._traditional_to_camelot_map[key]

    def camelot(self) -> str:
        if self._notation_type == TrackKey.NOTATION_CAMELOT:
            return self._key.upper()

        return self._traditional_to_camelot(self._key)

class DatabaseEntry:
    _fields: dict[str, bytes]

    def __init__(self, fields: dict[str, bytes]):
        self._fields = fields

    def key(self) -> TrackKey:
        return TrackKey(self._fields.get("tkey", b"").decode("utf-16-be"))

    def location(self) -> str:
        return self._fields["pfil"].decode("utf-16-be")

class Database:
    _tracks: dict[str, DatabaseEntry]

    def __init__(self, tracks: list[DatabaseEntry]):
        self._tracks = {}

        for track in tracks:
            self._tracks[track.location()] = track

    def get_track(self, location: str) -> DatabaseEntry:
        return self._tracks.get(location, None)


def prettify(elem):
    rough_string = tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

def generate_rekordbox_xml(processed_data, copy_to_memory_cues):
    root = Element('DJ_PLAYLISTS', Version="1.0.0")
    _ = SubElement(root, 'PRODUCT', Name="rekordbox", Version="6.7.4", Company="AlphaTheta")
    collection = SubElement(root, 'COLLECTION', Entries=str(len(processed_data)))
    playlists = SubElement(root, 'PLAYLISTS')
    root_playlist = SubElement(
        playlists, 'NODE', Type="0", Name="ROOT",
        Count=str(len(processed_data)),
    )

    track_id = 1
    for playlist_name, tracks in processed_data.items():
        playlist_elem = SubElement(
            root_playlist, 'NODE', Name=playlist_name,
            Type="1", KeyType="0", Entries=str(len(tracks)),
        )

        for track in tracks:
            full_file_path = "file://localhost" + os.path.join(os.getcwd(), track['file_location'])

            track_elem = SubElement(
                collection, 'TRACK', TrackID=str(track_id), Name=track['title'].strip(),
                Artist=track['artist'].strip(), Kind="MP3 File", TotalTime=track['totalTime'],
                Tonality=track["tonality"], Location=full_file_path,
            )

            for hot_cue in track.get('hot_cues', []):
                SubElement(
                    track_elem, 'POSITION_MARK', Name=hot_cue['name'], Type="0",
                    Start=str(round(hot_cue['position_ms'] / 1000, 3)),
                    Num=str(hot_cue['index']),
                    Red=str(int(hot_cue['color'][1:3], 16)),
                    Green=str(int(hot_cue['color'][3:5], 16)),
                    Blue=str(int(hot_cue['color'][5:7], 16)),
                )

                if copy_to_memory_cues:
                    SubElement(
                        track_elem, 'POSITION_MARK', Name=hot_cue['name'], Type="0",
                        Start=str(round(hot_cue['position_ms'] / 1000, 3)),
                        Num=str(MEMORY_CUE_ID),
                        Red=str(int(hot_cue['color'][1:3], 16)),
                        Green=str(int(hot_cue['color'][3:5], 16)),
                        Blue=str(int(hot_cue['color'][5:7], 16)),
                    )

            SubElement(playlist_elem, 'TRACK', Key=str(track_id))
            track_id += 1

    with open(DEFAULT_OUTPUT_FILE_NAME, "w", encoding='utf-8') as xml_output:
        xml_output.write(prettify(root))

def find_serato_crates(serato_folder_path):
    crate_file_paths = []
    for root, _, files in os.walk(serato_folder_path):
        for file in files:
            if file.endswith('.crate'):
                full_path = os.path.join(root, file)
                crate_file_paths.append(full_path)

    return crate_file_paths

def has_equal_bytes_at(idx, bytes_array, subset):
    if (idx < len(bytes_array) - len(subset) and
       all(bytes_array[idx + i] == subset[i] for i in range(len(subset)))):
        return True

    return False

def extract_file_paths_from_crate(crate_file_path, encoding='utf-16-be'):
    with open(crate_file_path, 'rb') as crate:
        bytes_of_file = crate.read()

    bytes_length = len(bytes_of_file)
    i = 0
    results = []

    while i < bytes_length - START_MARKER_FULL_LENGTH:
        if has_equal_bytes_at(i, bytes_of_file, START_MARKER):
            i += len(START_MARKER)
            path_size = struct.unpack('>I', bytes_of_file[i:i + PATH_LENGTH_OFFSET])[0]
            i += PATH_LENGTH_OFFSET

            audio_path = bytes_of_file[i:i + path_size].decode(encoding)
            results.append(audio_path)

            i += path_size

        i += 1

    return results

def extract_m4a_metadata(track):
    audio = MP4(track)

    audio_metadata = {
        'TIT2': audio.get('\xa9nam', ['Unknown Title'])[0],
        'TPE1': audio.get('\xa9ART', ['Unknown Artist'])[0],
        'TBPM': audio.get('tmpo', ['Unknown BPM'])[0],
        'TotalTime': round(audio.info.length)
    }

    # Check for both '----:com.serato:markersv2' and '----:com.serato.dj:markersv2'
    serato_markers_base64 = audio.get('----:com.serato:markersv2', [None])[0]
    if serato_markers_base64 is None:
        serato_markers_base64 = audio.get('----:com.serato.dj:markersv2', [None])[0]

    if serato_markers_base64:
        hot_cues = parse_serato_hot_cues(serato_markers_base64, track)
        return audio_metadata, hot_cues

    return audio_metadata, []

def extract_mp3_metadata(track):
    try:
        audio = ID3(track)
    except Exception as err:
        print(f"Warning: Unable to read ID3 tags from {track} due to {err}")
        return {}, []

    audio_metadata = {}
    hot_cues = []

    for tag_name in ['TIT2', 'TPE1', 'TALB', 'TBPM']:
        try:
            tag = audio.get(tag_name, 'Unknown')
            if hasattr(tag, 'text'):
                audio_metadata[tag_name] = tag.text[0]
            else:
                if tag_name in ("TIT2", "TPE1") and tag != 'Unknown':  # Ignore TALB warnings
                    print(f"Warning: Tag {tag_name} not properly formatted in file {track}.")
                audio_metadata[tag_name] = 'Unknown'
        except Exception as err:
            print(f"Warning: An issue occurred while reading {tag_name} from {track}: {err}")

    for tag in audio.values():
        if tag.FrameID == 'GEOB':
            if tag.desc == 'Serato Markers2':
                try:
                    hot_cues = parse_serato_hot_cues(tag.data, track)
                except Exception as err:
                    print(
                        f"""Warning: An issue occurred while reading
                        Serato Markers2 from {track}: {err}"""
                    )

    return audio_metadata, hot_cues

def parse_serato_hot_cues(base64_data, track):
    # Remove non-base64 characters
    clean_base64_data = re.sub(r'[^a-zA-Z0-9+/=]', '', base64_data.decode('utf-8'))

    # It looks like Serato pads with zeros instead of '=', something then drops
    # these zeros and we get an invalid base64 strings. Here's a workaround
    padding_needed = 4 - len(clean_base64_data) % 4
    if padding_needed != 4:
        clean_base64_data += "A" * padding_needed

    try:
        data = base64.b64decode(clean_base64_data)
    except Exception as err:
        print(f"Error decoding base64 data: {err} {track}")
        return []

    index = 0
    hot_cues = []

    while index < len(data):
        next_null = data[index:].find(b'\x00')
        if next_null == -1:
            print("Reached end of data")
            break

        entry_type = data[index:index + next_null].decode('utf-8')
        index += len(entry_type) + 1

        if index + 4 > len(data):
            break

        entry_len = struct.unpack('>I', data[index:index + 4])[0]
        index += 4  # Move past the length field

        if entry_type == 'CUE':
            hot_cue_data = data[index:index + entry_len]

            hotcue_index = hot_cue_data[1]
            position_ms = struct.unpack('>I', hot_cue_data[2:6])[0]

            color_data = hot_cue_data[7:10]
            color_hex = f"#{color_data[0]:02X}{color_data[1]:02X}{color_data[2]:02X}"

            hotcue_name = hot_cue_data[12:-1].decode('utf8')

            hot_cues.append({
                'name': hotcue_name,
                'index': hotcue_index,
                'position_ms': position_ms,
                'color': color_hex,
            })

        index += entry_len

    return hot_cues

def parse_serato_database(path: str) -> Database:
    with open(path, 'rb') as database:
        # skip header
        database.seek(4, 1)

        header_length_bytes = database.read(4)
        header_length = struct.unpack(">I", header_length_bytes)[0]
        database.seek(header_length, 1)

        tracks = []

        # read tracks
        while True:
            otrk = database.read(4).decode('utf8')
            if otrk != "otrk":
                # reached EOF
                break

            otrk_bytes = database.read(4)
            otrk = struct.unpack(">I", otrk_bytes)[0]

            read_bytes = 0
            track_fields = {}

            while read_bytes < otrk:
                key = database.read(4).decode('utf8')

                value_length_bytes = database.read(4)
                value_length = struct.unpack(">I", value_length_bytes)[0]
                value = database.read(value_length)

                track_fields[key] = value
                read_bytes += 4 + 4 + value_length

            tracks.append(DatabaseEntry(track_fields))

    return Database(tracks)


def get_cmd_args():
    parser = argparse.ArgumentParser(
        prog='serato_to_rekordbox_converter',
        description='Converts your serato crates to rekorkdbox playlists, cues included',
    )

    parser.add_argument(
        "--serato", default=DEFAULT_SERATO_FOLDER_PATH,
        help="path to serato database",
    )
    parser.add_argument(
        "--volume", default=DEFAULT_VOLUME_WITH_TRACKS,
        help="root dir of the volume with tracks",
    )
    parser.add_argument(
        "--memory", default=DEFAULT_COPY_TO_MEMORY_CUES,
        help="copy hot cues to memory cues",
    )

    return parser.parse_args()

def main(argc: int, argv: list[str]):
    args = get_cmd_args()

    serato_crate_paths = find_serato_crates(args.serato)

    processed_serato_files = {}
    unsuccessful_conversions = []

    database = parse_serato_database(os.path.join(args.serato, SERATO_DATABASE_FILE_NAME))

    for path in serato_crate_paths:
        # Remove '.crate' from the filename to get the playlist name
        playlist_name = os.path.basename(path)[:-6].replace("%%", "/")
        print("Converting: " + playlist_name)

        # Initialize the playlist entry in processed_serato_files if not already present
        if playlist_name not in processed_serato_files:
            processed_serato_files[playlist_name] = []

        for path_to_track in extract_file_paths_from_crate(path):
            real_path_to_track = os.path.join(args.volume, path_to_track)
            audio_metadata = {}
            hot_cues = []

            try:
                if path_to_track.lower().endswith('.mp3'):
                    audio_metadata, hot_cues = extract_mp3_metadata(real_path_to_track)
                elif path_to_track.lower().endswith('.m4a'):
                    audio_metadata, hot_cues = extract_m4a_metadata(real_path_to_track)
                else:
                    unsuccessful_conversions.append(path_to_track)
                    continue

                song_title = audio_metadata.get('TIT2', 'Unknown Title')
                song_artist = audio_metadata.get('TPE1', 'Unknown Artist')
                key_in_camelot = database.get_track(path_to_track).key().camelot()

                total_time = None

                if path_to_track.lower().endswith('.mp3'):
                    audio = MP3(real_path_to_track)
                    total_time = round(audio.info.length)
                elif path_to_track.lower().endswith('.m4a'):
                    audio = MP4(real_path_to_track)
                    total_time = round(audio.info.length)
                else:
                    raise Exception("Invalid format type")

                processed_serato_files[playlist_name].append({
                    'file_location': real_path_to_track,
                    'title': song_title,
                    'artist': song_artist,
                    'hot_cues': hot_cues,
                    'totalTime': str(total_time),
                    'tonality': key_in_camelot
                })

            except Exception as err:
                print(f"An exception occurred for track {path_to_track}: {err}")
                unsuccessful_conversions.append(path_to_track)

    generate_rekordbox_xml(processed_serato_files, args.memory)
    print("\nOutput successfully generated: Serato_Converted.xml\n")

    # Print the unsuccessful conversions
    if unsuccessful_conversions:
        print(
            """The following files have not been converted (corrupt / unrecognised metadata,
             unsupported format, missing file etc): """
        )
        for track in unsuccessful_conversions:
            print(track)


if __name__ == "__main__":
    main(len(sys.argv), sys.argv)
