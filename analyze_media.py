import subprocess
import json
import sys
import os
import re


def analyze_file_with_ffprobe(file_path, ffprobe_path):
    """Analyze a media file using ffprobe with multiple approaches to extract all possible metadata."""

    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        return

    if not os.path.exists(ffprobe_path):
        print(f"Error: ffprobe not found at: {ffprobe_path}")
        return

    print(f"Analyzing file: {file_path}")
    print(f"Using ffprobe: {ffprobe_path}\n")

    # Standard command to extract all available metadata
    all_data_command = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-show_programs",
        "-show_chapters",
        file_path
    ]

    # Detailed metadata extraction command
    detailed_command = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-show_programs",
        "-show_private_data",  # Try to extract private data
        "-show_entries",
        "frame=pkt_pts_time,pkt_dts_time,pkt_duration_time,pkt_pos,pkt_size,pict_type,key_frame,interlaced_frame",
        file_path
    ]

    # Dump all packets command
    packets_command = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_packets",
        "-read_intervals", "%+5",  # Only first 5 seconds to keep output manageable
        file_path
    ]

    # Timecode-specific command
    tc_command = [
        ffprobe_path,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream_tags=timecode:format_tags=timecode:stream_side_data=timecode",
        "-of", "json",
        file_path
    ]

    # Try to extract frame timecodes command (first few frames)
    frame_tc_command = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-select_streams", "v:0",
        "-read_intervals", "%+#10",  # First 10 frames
        "-show_frames",
        "-show_entries", "frame=pkt_pts_time,pkt_dts_time,best_effort_timestamp_time",
        file_path
    ]

    # XML output (might have different data format)
    xml_command = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "xml",
        "-show_format",
        "-show_streams",
        file_path
    ]

    # Raw format dump (check for any hidden metadata)
    raw_command = [
        ffprobe_path,
        "-v", "error",
        "-i", file_path
    ]

    try:
        # Run the main command for all data
        print("=== FULL FFPROBE OUTPUT ===")
        result = subprocess.run(all_data_command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print("Error parsing JSON output")
                print("Raw output:", result.stdout)
        else:
            print(f"Error executing ffprobe: {result.stderr}")
        print()

        # Run detailed metadata command
        print("=== DETAILED METADATA ===")
        result = subprocess.run(detailed_command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                # Filter out excessively large output sections
                if "frames" in data and len(data["frames"]) > 5:
                    print(f"Found {len(data['frames'])} frames. Showing first 5:")
                    data["frames"] = data["frames"][:5]
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print("Error parsing JSON output")
                print("Raw output:", result.stdout[:1000])  # Show first 1000 chars
        else:
            print(f"Error executing ffprobe: {result.stderr}")
        print()

        # Run packets command
        print("=== PACKET DATA (FIRST FEW SECONDS) ===")
        result = subprocess.run(packets_command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                # Filter out excessively large output
                if "packets" in data and len(data["packets"]) > 5:
                    print(f"Found {len(data['packets'])} packets. Showing first 5:")
                    data["packets"] = data["packets"][:5]
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print("Error parsing JSON output")
                print("Raw output:", result.stdout[:1000])  # Show first 1000 chars
        else:
            print(f"Error executing ffprobe: {result.stderr}")
        print()

        # Run timecode-specific command
        print("=== TIMECODE SPECIFIC INFORMATION ===")
        result = subprocess.run(tc_command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print("Error parsing JSON output")
                print("Raw output:", result.stdout)
        else:
            print(f"Error executing ffprobe: {result.stderr}")
        print()

        # Run frame timecode command
        print("=== FIRST 10 FRAMES TIMING DATA ===")
        result = subprocess.run(frame_tc_command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print("Error parsing JSON output")
                print("Raw output:", result.stdout[:1000])
        else:
            print(f"Error executing ffprobe: {result.stderr}")
        print()

        # Run XML format command (might expose different metadata)
        print("=== XML FORMAT OUTPUT ===")
        result = subprocess.run(xml_command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            print(result.stdout[:2000])  # Show first 2000 chars of XML
            # Check for timecode-related patterns in XML
            tc_patterns = ["timecode", "time_code", "time code", "TC", "tc=", "start_time"]
            for pattern in tc_patterns:
                matches = re.findall(r'[^>]*' + pattern + r'[^<]*', result.stdout)
                if matches:
                    print(f"\nFound potential timecode references in XML:")
                    for match in matches:
                        print(f"  {match.strip()}")
        else:
            print(f"Error executing ffprobe: {result.stderr}")
        print()

        # Run raw format dump (might expose hidden metadata)
        print("=== RAW FORMAT DUMP ===")
        result = subprocess.run(raw_command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            if result.stderr:  # ffprobe outputs to stderr for this command
                # Search for timecode or time-related information
                tc_lines = []
                for line in result.stderr.splitlines():
                    if any(x in line.lower() for x in ["time", "timecode", "tc", "pts", "dts", "clock"]):
                        tc_lines.append(line)

                print("Raw output (filtered for time-related info):")
                if tc_lines:
                    for line in tc_lines:
                        print(line)
                else:
                    print("No time-related information found in raw output")
                    print("First 30 lines of raw output:")
                    print("\n".join(result.stderr.splitlines()[:30]))
            else:
                print("No output from raw format dump")
        else:
            print(f"Error executing ffprobe: {result.stderr}")
        print()

        # Final attempt: try to extract QuickTime atoms (MOV/MP4 metadata)
        if file_path.lower().endswith(('.mov', '.mp4', '.m4v')):
            print("=== QUICKTIME METADATA EXTRACTION (ATOM DUMP) ===")
            # This requires special handling with ffprobe
            qt_command = [
                ffprobe_path,
                "-v", "trace",
                "-i", file_path
            ]

            result = subprocess.run(qt_command, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                # Filter output for QuickTime atom data
                atom_data = []
                for line in result.stderr.splitlines():
                    if any(x in line.lower() for x in ["atom", "moov", "mvhd", "trak", "timecode", "time"]):
                        atom_data.append(line)

                if atom_data:
                    print("QuickTime atom data (filtered for time/timecode):")
                    for line in atom_data:
                        print(line)
                else:
                    print("No relevant QuickTime atom data found")
            else:
                print(f"Error executing ffprobe for QuickTime metadata: {result.stderr}")
            print()

        print("Analysis complete.")

    except Exception as e:
        print(f"Error during ffprobe analysis: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analyze_media.py <file_path> <ffprobe_path>")
        print(
            "Example: python analyze_media.py \"C:\\path\\to\\video.mp4\" \"D:\\code\\TimelineHarvester\\ffmpeg_bin\\ffprobe.exe\"")
        sys.exit(1)

    file_path = sys.argv[1]
    ffprobe_path = sys.argv[2]
    analyze_file_with_ffprobe(file_path, ffprobe_path)