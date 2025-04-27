import os
import json
import asyncio
import pandas as pd
from dash import Dash, dcc, html, dash_table, Output, Input
import websockets
from threading import Thread

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
    return mmsi.startswith(('2', '3', '4'))

async def ais_stream_consumer():
    async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
        subscription = {
            "APIKey": os.getenv("AISSTREAM_API_KEY"),
            "BoundingBoxes": [[[lat-0.5, lon-0.5], [lat+0.5, lon+0.5]] 
                            for lat, lon in PORT_COORDINATES.values()],
            "FilterMessageTypes": ["PositionReport"]
        }
        await websocket.send(json.dumps(subscription))
        
        async for message in websocket:
            data = json.loads(message)
            if data["MessageType"] == "PositionReport":
                vessel = data["Message"]["PositionReport"]
                metadata = data["Metadata"]
                
                if is_foreign_ship(str(vessel["UserID"])):
                    new_row = {
                        "MMSI": vessel["UserID"],
                        "Ship Name": metadata.get("ShipName", "Unknown"),
                        "Latitude": vessel["Latitude"],
                        "Longitude": vessel["Longitude"],
                        "Speed": vessel["Sog"],
                        "Course": vessel["Cog"],
                        "Port": "Unknown"
                    }
                    
                    current_pos = (vessel["Latitude"], vessel["Longitude"])
                    new_row["Port"] = min(PORT_COORDINATES.items(),
                                        key=lambda x: abs(x[1][0]-current_pos[0]) + 
                                                       abs(x[1][1]-current_pos[1]))[0]
                    
                    app.vessels.append(new_row)
                    app.vessels = app.vessels[-1000:]

def start_websocket():
    asyncio.new_event_loop().run_until_complete(ais_stream_consumer())

# Dash app setup
app = Dash(__name__)
server = app.server
app.vessels = []

# Start WebSocket thread
Thread(target=start_websocket, daemon=True).start()

app.layout = html.Div([
    html.H1("Foreign Ships at Top 10 Busiest US Ports"),
    dcc.Interval(id='interval-update', interval=5*1000),
    dash_table.DataTable(
        id='vessel-table',
        columns=[
            {"name": "MMSI", "id": "MMSI"},
            {"name": "Ship Name", "id": "Ship Name"},
            {"name": "Port", "id": "Port"},
            {"name": "Speed", "id": "Speed"},
            {"name": "Course", "id": "Course"}
        ],
        data=[],
        page_size=20
    )
])

@app.callback(
    Output('vessel-table', 'data'),
    Input('interval-update', 'n_intervals')
)
def update_table(n):
    return app.vessels[-100:]

if __name__ == "__main__":
    app.run_server(debug=False)
