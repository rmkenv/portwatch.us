import os
import requests
import pandas as pd
from dash import Dash, dcc, html, dash_table, Output, Input

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

def is_foreign_ship(mmsi: str) -> bool:
    return mmsi.startswith(('2', '3', '4'))  # Non-US country codes

def fetch_ais_data(api_key):
    # Replace with the actual endpoint and parameters for aisstream.io
    url = "https://stream.aisstream.io/v0/broadcast"  # Example endpoint
    headers = {"Authorization": f"Bearer {api_key}"}
    # This is a placeholder; adapt to the actual API
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return []
    data = response.json()
    vessels = []
    for item in data.get("messages", []):
        vessel = item.get("PositionReport", {})
        metadata = item.get("Metadata", {})
        mmsi = str(vessel.get("UserID", ""))
        if is_foreign_ship(mmsi):
            lat, lon = vessel.get("Latitude"), vessel.get("Longitude")
            # Find nearest port
            port = min(PORT_COORDINATES.items(), key=lambda x: abs(x[1][0]-lat) + abs(x[1][1]-lon))[0]
            vessels.append({
                "MMSI": mmsi,
                "Ship Name": metadata.get("ShipName", "Unknown"),
                "Latitude": lat,
                "Longitude": lon,
                "Speed": vessel.get("Sog"),
                "Course": vessel.get("Cog"),
                "Port": port
            })
    return vessels

# Dash app setup
app = Dash(__name__)
server = app.server  # For Render deployment

app.layout = html.Div([
    html.H1("Foreign Ships at Top 10 Busiest US Ports"),
    dcc.Dropdown(
        id="port-filter",
        options=[{"label": k, "value": k} for k in PORT_COORDINATES.keys()],
        value=list(PORT_COORDINATES.keys()),
        multi=True,
        placeholder="Select ports to filter"
    ),
    dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0),  # Poll every 60 seconds
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
        style_table={'overflowX': 'auto'}
    )
])

@app.callback(
    Output('vessel-table', 'data'),
    Input('interval-component', 'n_intervals'),
    Input('port-filter', 'value')
)
def update_table(n_intervals, selected_ports):
    api_key = os.getenv("AISSTREAM_API_KEY")
    if not api_key:
        return []
    vessels = fetch_ais_data(api_key)
    filtered = [v for v in vessels if v["Port"] in selected_ports]
    return filtered

if __name__ == "__main__":
    app.run_server(debug=False)
