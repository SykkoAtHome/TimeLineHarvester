import subprocess
import json
import sys
import os


def analyze_file_with_ffprobe(file_path, ffprobe_path):
    """Analyze a media file using ffprobe and print all available metadata."""

    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        return

    if not os.path.exists(ffprobe_path):
        print(f"Error: ffprobe not found at: {ffprobe_path}")
        return

    # Standard command to extract all available metadata
    command = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-show_programs",
        "-show_chapters",
        file_path
    ]

    # Add a command to specifically look for timecode information
    tc_command = [
        ffprobe_path,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream_tags=timecode:format_tags=timecode",
        "-of", "json",
        file_path
    ]

    print(f"Analyzing file: {file_path}\n")
    print(f"Using ffprobe: {ffprobe_path}\n")

    try:
        # Run the main command
        result = subprocess.run(command, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            print(f"Error executing ffprobe: {result.stderr}")
            return

        # Parse JSON output
        try:
            data = json.loads(result.stdout)
            print("=== FULL FFPROBE OUTPUT ===")
            print(json.dumps(data, indent=2))
            print()

            # Print some specific information that might be helpful
            print("=== KEY INFORMATION ===")

            # Check for streams
            if "streams" in data:
                for i, stream in enumerate(data["streams"]):
                    print(f"Stream #{i}: Type: {stream.get('codec_type', 'unknown')}")
                    print(f"  Codec: {stream.get('codec_name', 'unknown')}")
                    print(f"  Duration: {stream.get('duration', 'unknown')}")
                    print(
                        f"  Frame Rate: {stream.get('r_frame_rate', 'unknown')} / {stream.get('avg_frame_rate', 'unknown')}")

                    # Check for timecode in stream tags
                    if "tags" in stream:
                        print(f"  Tags: {json.dumps(stream['tags'], indent=2)}")
                        if "timecode" in stream["tags"]:
                            print(f"  TIMECODE: {stream['tags']['timecode']}")
                    print()

            # Check format info
            if "format" in data:
                print("Format information:")
                print(f"  Format name: {data['format'].get('format_name', 'unknown')}")
                print(f"  Duration: {data['format'].get('duration', 'unknown')}")
                print(f"  Start time: {data['format'].get('start_time', 'unknown')}")

                # Check for timecode in format tags
                if "tags" in data["format"]:
                    print(f"  Format tags: {json.dumps(data['format']['tags'], indent=2)}")
                    if "timecode" in data["format"]["tags"]:
                        print(f"  FORMAT TIMECODE: {data['format']['tags']['timecode']}")
                print()

        except json.JSONDecodeError as e:
            print(f"Error parsing JSON output: {e}")
            print("Raw output:", result.stdout)
            return

        # Run the timecode-specific command
        tc_result = subprocess.run(tc_command, capture_output=True, text=True, check=False)

        if tc_result.returncode == 0:
            try:
                tc_data = json.loads(tc_result.stdout)
                print("=== TIMECODE SPECIFIC INFORMATION ===")
                print(json.dumps(tc_data, indent=2))
                print()
            except json.JSONDecodeError:
                print("No valid JSON from timecode command")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analyze_media.py <file_path> <ffprobe_path>")
        print(
            "Example: python analyze_media.py \"C:\\path\\to\\video.mp4\" \"D:\\code\\TimelineHarvester\\ffmpeg_bin\\ffprobe.exe\"")
        sys.exit(1)

    file_path = sys.argv[1]
    ffprobe_path = sys.argv[2]
    analyze_file_with_ffprobe(file_path, ffprobe_path)