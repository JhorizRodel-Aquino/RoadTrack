import requests
import time

def request_geocode(lat, lon):
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1
    }
    headers = {
        "User-Agent": "ARCDEM-GIS-WebApp/1.0 (jhorizrodel.aquino@cvsu.edu.ph)"  # Required by Nominatim
    }

    response = requests.get(url, params=params, headers=headers)
    data = response.json()

    time.sleep(1)

    address = data.get("address", {})

    result = {
        "city": address.get("city") or address.get("town") or address.get("municipality") or "no city",
        "province": address.get("state") or "no province",
        "region": address.get("region") or "no region", 
    }

    return result


print(request_geocode(12.5755, 122.2696))