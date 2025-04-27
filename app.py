import streamlit as st
import websockets
import json
import asyncio
import pandas as pd
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
    """Check if ship is foreign using MMSI country code"""
    return mmsi.startswith(('2', '3', '4'))  # Non-US country codes

async def ais_stream_consumer():
    async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
        subscription = {
            "APIKey": st.secrets["AISSTREAM_API_KEY"],
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
                    
                    # Determine nearest port
                    current_pos = (vessel["Latitude"], vessel["Longitude"])
                    new_row["Port"] = min(PORT_COORDINATES.items(),
                                        key=lambda x: abs(x[1][0]-current_pos[0]) + 
                                                       abs(x[1][1]-current_pos[1]))[0]
                    
                    st.session_state.vessels.append(new_row)
                    st.session_state.vessels = st.session_state.vessels[-1000:]

def start_websocket():
    asyncio.new_event_loop().run_until_complete(ais_stream_consumer())

# Streamlit UI Configuration
st.set_page_config(page_title="Maritime Monitor", layout="wide")
st.title("🚢 Real-Time Foreign Vessel Tracking")
st.markdown("Monitoring top 10 US ports using AISStream.io")

# Initialize session state
if "vessels" not in st.session_state:
    st.session_state.vessels = []

# Start WebSocket thread
if not st.session_state.get("ws_running"):
    Thread(target=start_websocket, daemon=True).start()
    st.session_state.ws_running = True

# Dashboard Layout
col1, col2 = st.columns([3, 2])

with col1:
    st.subheader("Live Ship Positions")
    if st.session_state.vessels:
        st.map(pd.DataFrame(st.session_state.vessels), 
              latitude='Latitude', longitude='Longitude',
              color='#FF0000', size=15)
    else:
        st.info("Awaiting vessel data...")

with col2:
    st.subheader("Vessel Details")
    port_filter = st.multiselect("Filter by Port", 
                                options=list(PORT_COORDINATES.keys()),
                                default=list(PORT_COORDINATES.keys()))
    
    filtered_data = [v for v in st.session_state.vessels 
                    if v["Port"] in port_filter] if port_filter else st.session_state.vessels
    
    if filtered_data:
        st.dataframe(pd.DataFrame(filtered_data)[["MMSI", "Ship Name", "Port", "Speed", "Course"]],
                    height=600,
                    column_config={
                        "Speed": st.column_config.ProgressColumn(
                            format="%.1f knots",
                            min_value=0,
                            max_value=30
                        )
                    })
    else:
        st.warning("No vessels in selected ports")
