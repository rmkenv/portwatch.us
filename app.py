import os
import json
import pandas as pd
import websocket
import threading
import time
from dash import Dash, dcc, html, dash_table, Output, Input, State
from collections import deque

# Top 10 US ports with coordinates (latitude, longitude)
PORT_COORDINATES = {
    "Los Angeles": (33.7490, -118.2645),
    "New York/New Jersey": (40.6699, -74.1863),
    "Long Beach": (33.7549, -118.2187),
    "Savannah": (32.0285, -81.1499),
    "Norfolk": (36.8844, -76.3309),
    "Houston": (29.6113, -94.9895),
    "Seattle": (47.2452, -122.4593),
    "Charleston": (32.7789, -79.9278),
    "Oakland": (37.7955, -122.2807),
    "Miami": (25.7788, -80.1780)
}

# Global vessel data store with thread safety
vessel_data_lock = threading.Lock()
vessel_data = {}  # MMSI -> vessel data
max_vessels = 1000  # Maximum number of vessels to track
last_update_time = 0

def is_foreign_ship(mmsi: str) -> bool:
    return mmsi.startswith(('2', '3', '4'))  # Non-US country codes

def find_nearest_port(lat, lon):
    return min(PORT_COORDINATES.items(), key=lambda x: abs(x[1][0]-lat) + abs(x[1][1]-lon))[0]

def on_message(ws, message):
    global vessel_data, last_update_time
    try:
        data = json.loads(message)

        # Check if this is a position report
        if "Message" in data and "PositionReport" in data["Message"]:
            position = data["Message"]["PositionReport"]
            metadata = data["MetaData"]

            mmsi = str(position.get("UserID", ""))

            # Only process foreign ships
            if is_foreign_ship(mmsi):
                lat = position.get("Latitude")
                lon = position.get("Longitude")

                # Skip if missing critical data
                if lat is None or lon is None:
                    return

                # Find nearest port
                port = find_nearest_port(lat, lon)

                vessel_info = {
                    "MMSI": mmsi,
                    "Ship Name": metadata.get("ShipName", "Unknown"),
                    "Latitude": lat,
                    "Longitude": lon,
                    "Speed": position.get("Sog"),
                    "Course": position.get("Cog"),
                    "Port": port,
                    "Last Updated": time.time()
                }

                # Thread-safe update of vessel data
                with vessel_data_lock:
                    vessel_data[mmsi] = vessel_info

                    # Limit the number of vessels we track
                    if len(vessel_data) > max_vessels:
                        # Remove oldest entries
                        oldest_mmsis = sorted(vessel_data.keys(),
                                             key=lambda k: vessel_data[k].get("Last Updated", 0))[:len(vessel_data) - max_vessels]
                        for old_mmsi in oldest_mmsis:
                            del vessel_data[old_mmsi]

                last_update_time = time.time()
    except Exception as e:
        print(f"Error processing message: {str(e)}")

def on_error(ws, error):
    print(f"WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"WebSocket closed: {close_status_code} - {close_msg}")

def on_open(ws):
    print("WebSocket connection established")
    # Subscribe to all position reports
    subscribe_message = {
        "APIKey": os.getenv("AISSTREAM_API_KEY", ""),
        "BoundingBoxes": [[[-180, -90], [180, 90]]]  # Global coverage
    }
    ws.send(json.dumps(subscribe_message))
    print("Subscription message sent")

def start_websocket():
    global ws
    api_key = os.getenv("AISSTREAM_API_KEY")
    if not api_key:
        print("Warning: AISSTREAM_API_KEY not set. WebSocket connection will fail.")
        return

    # Create WebSocket connection
    ws = websocket.WebSocketApp("wss://stream.aisstream.io/v0/stream",
                                on_open=on_open,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)

    # Start WebSocket in a separate thread
    wst = threading.Thread(target=ws.run_forever)
    wst.daemon = True
    wst.start()

# Sample data for testing without API key
sample_data = [
    {
        "MMSI": "220123456",
        "Ship Name": "Sample Vessel 1",
        "Latitude": 33.75,
        "Longitude": -118.26,
        "Speed": 12.5,
        "Course": 180,
        "Port": "Los Angeles",
        "Last Updated": time.time()
    },
    {
        "MMSI": "345678901",
        "Ship Name": "Sample Vessel 2",
        "Latitude": 40.67,
        "Longitude": -74.18,
        "Speed": 8.3,
        "Course": 90,
        "Port": "New York/New Jersey",
        "Last Updated": time.time()
    }
]

# Dash app setup
app = Dash(__name__)
server = app.server  # For Render deployment

app.layout = html.Div([
    html.H1("Foreign Ships at Top 10 Busiest US Ports"),
    html.Div(id="status-message", style={"color": "red"}),
    html.Div([
        html.Span("Last updated: "),
        html.Span(id="last-update-time")
    ]),
    dcc.Dropdown(
        id="port-filter",
        options=[{"label": k, "value": k} for k in PORT_COORDINATES.keys()],
        value=list(PORT_COORDINATES.keys()),
        multi=True,
        placeholder="Select ports to filter"
    ),
    dcc.Interval(id='interval-component', interval=5000, n_intervals=0),  # Update UI every 5 seconds
    dash_table.DataTable(
        id='vessel-table',
        columns=[
            {"name": "MMSI", "id": "MMSI"},
            {"name": "Ship Name", "id": "Ship Name"},
            {"name": "Port", "id": "Port"},
            {"name": "Speed", "id": "Speed"},
            {"name": "Course", "id": "Course"},
            {"name": "Latitude", "id": "Latitude"},
            {"name": "Longitude", "id": "Longitude"},
        ],
        data=[],
        page_size=20,
        style_table={'overflowX': 'auto'},
        sort_action='native'
    )
])

@app.callback(
    [Output('vessel-table', 'data'),
     Output('status-message', 'children'),
     Output('last-update-time', 'children')],
    [Input('interval-component', 'n_intervals'),
     Input('port-filter', 'value')]
)
def update_table(n_intervals, selected_ports):
    global vessel_data, last_update_time

    # Check if we have an API key
    api_key = os.getenv("AISSTREAM_API_KEY")
    status_message = ""

    if not api_key:
        status_message = "Warning: AISSTREAM_API_KEY environment variable not set. Using sample data."
        # Use sample data if no API key
        filtered_vessels = [v for v in sample_data if v["Port"] in selected_ports]
        last_update = "N/A (using sample data)"
    else:
        # Get a thread-safe copy of the vessel data
        with vessel_data_lock:
            vessels = list(vessel_data.values())

        # Filter by selected ports
        filtered_vessels = [v for v in vessels if v["Port"] in selected_ports]

        if not vessels:
            status_message = "No vessel data received yet. Waiting for WebSocket data..."
        elif not filtered_vessels:
            status_message = "No vessels found for selected ports. Try selecting different ports."

        # Format the last update time
        if last_update_time > 0:
            last_update = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_update_time))
        else:
            last_update = "No data received yet"

    # Remove the "Last Updated" field before sending to the table
    for vessel in filtered_vessels:
        if "Last Updated" in vessel:
            vessel_copy = vessel.copy()
            vessel_copy.pop("Last Updated", None)

    return filtered_vessels, status_message, last_update

if __name__ == "__main__":
    print("Starting WebSocket connection...")
    start_websocket()

    print("Starting Dash server...")
    app.run_server(debug=True)  # Set debug=True for more information
