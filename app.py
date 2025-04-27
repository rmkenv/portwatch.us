import os
import json
import pandas as pd
import websocket
import threading
import time
import logging
from dash import Dash, dcc, html, dash_table, Output, Input, State
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

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
websocket_connected = False

# Sample data - always include this for fallback
sample_data = [
    {
        "MMSI": "220123456",
        "Ship Name": "Sample Vessel 1",
        "Latitude": 33.75,
        "Longitude": -118.26,
        "Speed": 12.5,
        "Course": 180,
        "Port": "Los Angeles"
    },
    {
        "MMSI": "345678901",
        "Ship Name": "Sample Vessel 2",
        "Latitude": 40.67,
        "Longitude": -74.18,
        "Speed": 8.3,
        "Course": 90,
        "Port": "New York/New Jersey"
    },
    {
        "MMSI": "412345678",
        "Ship Name": "Sample Vessel 3",
        "Latitude": 32.03,
        "Longitude": -81.15,
        "Speed": 0.0,
        "Course": 270,
        "Port": "Savannah"
    }
]

def is_foreign_ship(mmsi: str) -> bool:
    try:
        return mmsi.startswith(('2', '3', '4'))  # Non-US country codes
    except:
        return False

def find_nearest_port(lat, lon):
    try:
        return min(PORT_COORDINATES.items(), key=lambda x: abs(x[1][0]-lat) + abs(x[1][1]-lon))[0]
    except:
        return "Unknown"

def on_message(ws, message):
    global vessel_data, last_update_time
    try:
        data = json.loads(message)
        logger.info(f"Received message type: {type(data)}")

        # Check if this is a position report
        if "Message" in data and "PositionReport" in data["Message"]:
            position = data["Message"]["PositionReport"]
            metadata = data["MetaData"]

            mmsi = str(position.get("UserID", ""))
            logger.info(f"Processing position for MMSI: {mmsi}")

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
                    "Port": port
                }

                # Thread-safe update of vessel data
                with vessel_data_lock:
                    vessel_data[mmsi] = vessel_info
                    logger.info(f"Updated vessel data. Total vessels: {len(vessel_data)}")

                    # Limit the number of vessels we track
                    if len(vessel_data) > max_vessels:
                        # Remove oldest entries
                        oldest_mmsis = sorted(vessel_data.keys(),
                                             key=lambda k: vessel_data[k].get("Last Updated", 0))[:len(vessel_data) - max_vessels]
                        for old_mmsi in oldest_mmsis:
                            del vessel_data[old_mmsi]

                last_update_time = time.time()
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")

def on_error(ws, error):
    global websocket_connected
    websocket_connected = False
    logger.error(f"WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    global websocket_connected
    websocket_connected = False
    logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")

    # Try to reconnect after a delay
    time.sleep(5)
    start_websocket()

def on_open(ws):
    global websocket_connected
    websocket_connected = True
    logger.info("WebSocket connection established")

    # Subscribe to all position reports
    api_key = os.getenv("AISSTREAM_API_KEY", "")
    logger.info(f"Using API key: {'*' * (len(api_key) if api_key else 0)}")

    subscribe_message = {
        "APIKey": api_key,
        "BoundingBoxes": [[[-180, -90], [180, 90]]]  # Global coverage
    }
    ws.send(json.dumps(subscribe_message))
    logger.info("Subscription message sent")

def start_websocket():
    global websocket_connected

    api_key = os.getenv("AISSTREAM_API_KEY")
    if not api_key:
        logger.warning("AISSTREAM_API_KEY not set. WebSocket connection will fail.")
        return

    try:
        # Enable trace for debugging
        websocket.enableTrace(True)

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
        logger.info("WebSocket thread started")
    except Exception as e:
        logger.error(f"Error starting WebSocket: {str(e)}")

# Dash app setup
app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server  # For Render deployment

app.layout = html.Div([
    html.H1("Foreign Ships at Top 10 Busiest US Ports"),
    html.Div(id="status-message", style={"color": "red"}),
    html.Div([
        html.Span("WebSocket Status: "),
        html.Span(id="websocket-status")
    ]),
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
        data=sample_data,  # Initialize with sample data
        page_size=20,
        style_table={'overflowX': 'auto'},
        sort_action='native'
    )
])

@app.callback(
    [Output('vessel-table', 'data'),
     Output('status-message', 'children'),
     Output('last-update-time', 'children'),
     Output('websocket-status', 'children'),
     Output('websocket-status', 'style')],
    [Input('interval-component', 'n_intervals'),
     Input('port-filter', 'value')]
)
def update_table(n_intervals, selected_ports):
    global vessel_data, last_update_time, websocket_connected

    logger.info(f"Updating table. Interval: {n_intervals}, Selected ports: {selected_ports}")

    # Check if we have an API key
    api_key = os.getenv("AISSTREAM_API_KEY")
    status_message = ""

    # WebSocket status
    if websocket_connected:
        ws_status = "Connected"
        ws_style = {"color": "green"}
    else:
        ws_status = "Disconnected"
        ws_style = {"color": "red"}

    # If we have real data, use it
    with vessel_data_lock:
        vessels = list(vessel_data.values())
        logger.info(f"Current vessel count: {len(vessels)}")

    # If we have no real data, use sample data
    if not vessels:
        logger.info("No real vessel data, using sample data")
        vessels = sample_data
        status_message = "Using sample data. "

        if not api_key:
            status_message += "AISSTREAM_API_KEY not set."
        else:
            status_message += "Waiting for WebSocket data..."

    # Filter by selected ports
    filtered_vessels = [v for v in vessels if v["Port"] in selected_ports]
    logger.info(f"Filtered vessel count: {len(filtered_vessels)}")

    if not filtered_vessels:
        status_message += " No vessels found for selected ports. Try selecting different ports."

    # Format the last update time
    if last_update_time > 0:
        last_update = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_update_time))
    else:
        last_update = "No data received yet"

    return filtered_vessels, status_message, last_update, ws_status, ws_style

# Initialize the WebSocket connection when the module loads
logger.info("Initializing application")
start_websocket()

if __name__ == "__main__":
    logger.info("Starting Dash server...")
    app.run_server(debug=True)  # Set debug=True for more information
