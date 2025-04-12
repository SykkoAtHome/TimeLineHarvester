import opentimelineio as otio
from opentimelineio import opentime
import sys
import logging
import os

# Basic Logging Setup
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

def inspect_timeline(file_path: str):
    """Reads a file with OTIO and prints info about its clips."""
    print("-" * 80)
    print(f"INSPECTING FILE: {file_path}")
    print("-" * 80)

    if not os.path.exists(file_path):
        logging.error(f"File not found: {file_path}")
        return

    timeline: otio.schema.Timeline = None
    try:
        # Read the file
        result = otio.adapters.read_from_file(file_path)

        # Find the timeline object
        if isinstance(result, otio.schema.Timeline):
            timeline = result
        elif isinstance(result, otio.schema.SerializableCollection):
            logging.warning("OTIO returned a Collection, looking for the first timeline.")
            timeline = next(result.find_children(kind=otio.schema.Timeline), None)

        if not timeline:
            logging.error("No timeline found in the file.")
            return

        # Get basic timeline info
        seq_rate = 25.0 # Default
        seq_start_time = opentime.RationalTime(0, seq_rate)
        try:
            # Attempt to get rate more reliably
             if timeline.global_start_time and timeline.global_start_time.rate > 0:
                 seq_rate = timeline.global_start_time.rate
             # Fallback logic might be needed if global_start_time is missing rate
             seq_start_time = timeline.global_start_time or seq_start_time # Use read value or default

             # Ensure start time uses the determined rate
             if seq_start_time.rate != seq_rate:
                  seq_start_time = seq_start_time.rescaled_to(seq_rate)

        except Exception as e:
             logging.warning(f"Could not reliably determine sequence rate/start time: {e}. Using defaults.")


        print(f"Timeline Name: {timeline.name}")
        print(f"Sequence Rate: {seq_rate}")
        print(f"Sequence Global Start Time: {seq_start_time} ({seq_start_time.to_timecode(seq_rate)})")
        print("\n--- Clips ---")

        item_counter = 0
        # Iterate through clips on the timeline
        for clip in timeline.find_clips():
            item_counter += 1
            print(f"\n--- Clip #{item_counter} ---")
            print(f"  Name: {clip.name}")

            # Print Source Range (what OTIO thinks is the IN/OUT in the source media)
            source_range = clip.source_range
            print(f"  OTIO clip.source_range: {source_range}")
            if source_range:
                 try:
                      sr_rate = source_range.duration.rate if source_range.duration else source_range.start_time.rate
                      if sr_rate > 0:
                           print(f"    Start TC (source_range): {source_range.start_time.to_timecode(sr_rate)}")
                           print(f"    Duration (source_range): {source_range.duration.to_timecode(sr_rate)} ({source_range.duration.value} frames @ {sr_rate}fps)")
                      else: print("    (Invalid rate in source_range)")
                 except Exception as e: print(f"    Error formatting source_range: {e}")


            # Print Timeline Range (clip's position on sequence)
            try:
                # range_of_child should give absolute position
                timeline_range = timeline.range_of_child(clip)
                print(f"  OTIO timeline.range_of_child(): {timeline_range}")
                if timeline_range:
                     # Use sequence_rate determined earlier
                     if timeline_range.start_time.rate != seq_rate:
                          timeline_range = otio.opentime.TimeRange(
                               start_time=timeline_range.start_time.rescaled_to(seq_rate),
                               duration=timeline_range.duration.rescaled_to(seq_rate)
                          )
                     print(f"    Start TC (timeline): {timeline_range.start_time.to_timecode(seq_rate)}")
                     print(f"    End TC excl (timeline): {timeline_range.end_time_exclusive().to_timecode(seq_rate)}")
                     print(f"    Duration (timeline): {timeline_range.duration.to_timecode(seq_rate)} ({timeline_range.duration.value} frames @ {seq_rate}fps)")
            except Exception as e:
                print(f"  Error getting/formatting timeline range: {e}")


            # Print Media Reference Info
            media_ref = clip.media_reference
            print(f"  Media Reference Type: {type(media_ref).__name__}")
            if media_ref:
                print(f"    Name: {getattr(media_ref, 'name', 'N/A')}")
                # Available range SHOULD be the full range of the referenced file
                available_range = getattr(media_ref, 'available_range', None)
                print(f"    Available Range: {available_range}")
                if available_range:
                    try:
                         ar_rate = available_range.duration.rate if available_range.duration else available_range.start_time.rate
                         if ar_rate > 0:
                              print(f"      Start TC (available_range): {available_range.start_time.to_timecode(ar_rate)}")
                              print(f"      Duration (available_range): {available_range.duration.to_timecode(ar_rate)} ({available_range.duration.value} frames @ {ar_rate}fps)")
                         else: print("      (Invalid rate in available_range)")
                    except Exception as e: print(f"      Error formatting available_range: {e}")

                if isinstance(media_ref, otio.schema.ExternalReference):
                    print(f"    Target URL: {getattr(media_ref, 'target_url', 'N/A')}")
                try:
                     print(f"    Metadata: {getattr(media_ref, 'metadata', {})}")
                except Exception as e: print(f"    Error accessing metadata: {e}")


    except Exception as e:
        logging.error(f"Failed to process file {file_path}: {e}", exc_info=True)

# --- Files to Inspect ---
xml_file = r"A:\__ORYGINAL_POST__\VISA\8802_VISA_ZWYCIEZCY_2x30_2x15_2x6_Papaya\03_OFFLINE\na_CC\myairbridge-szD7fqeVQ1k\XML\VISA_ZWYCIEZCY_A_6_v2_tc.xml"
aaf_file = r"A:\__ORYGINAL_POST__\VISA\8802_VISA_ZWYCIEZCY_2x30_2x15_2x6_Papaya\03_OFFLINE\na_CC\myairbridge-szD7fqeVQ1k\VISA_ZWYCIEZCY_A_6_v2_tc.aaf"

# --- Run Inspection ---
inspect_timeline(xml_file)
inspect_timeline(aaf_file)

print("\n--- Inspection Complete ---")