"""
SATUSEHAT Patient Registration Script
Alur: Auth → Cari Pasien & Dokter → Buat Location → Buat Encounter
"""

import requests
import json
import uuid
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# Konfigurasi
# ─────────────────────────────────────────────
CLIENT_ID     = os.getenv("SATUSEHAT_CLIENT_ID", "3KV28sv3jGLlcIyX0pspInlAs6raEaDAqF2Miw2nB0jz9ZjP")
CLIENT_SECRET = os.getenv("SATUSEHAT_CLIENT_SECRET", "3RCFPOXQJwFAEAEfea5ZInDcJfA5Itg322ndxa1KkzHUM2x9zRTQWZ422NNskr4is")
ORG_ID        = os.getenv("SATUSEHAT_ORG_ID", "9c7605c1-8d6e-46a0-b798-32aedb2032e6")

BASE_AUTH_URL = "https://api-satusehat-stg.dto.kemkes.go.id/oauth2/v1"
BASE_FHIR_URL = "https://api-satusehat-stg.dto.kemkes.go.id/fhir-r4/v1"

NIK_PASIEN = "1000000000000007"
NIK_DOKTER = "7209061211900001"


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────
def log(step: str, msg: str):
    print(f"\n{'='*60}")
    print(f"  STEP {step}")
    print(f"{'='*60}")
    print(msg)

def handle_response(resp: requests.Response, label: str) -> dict:
    """Validasi response dan kembalikan JSON, atau raise error."""
    if resp.status_code == 401:
        raise Exception(f"[{label}] 401 Unauthorized — Token expired atau Client ID/Secret salah.")
    if resp.status_code == 404:
        raise Exception(f"[{label}] 404 Not Found — Resource tidak ditemukan.")
    if resp.status_code not in (200, 201):
        raise Exception(
            f"[{label}] Error {resp.status_code}:\n{json.dumps(resp.json(), indent=2)}"
        )
    return resp.json()


# ─────────────────────────────────────────────
# STEP 1: GET ACCESS TOKEN
# ─────────────────────────────────────────────
def get_access_token() -> str:
    log("1", "Mendapatkan Access Token dari SATUSEHAT OAuth2...")

    url  = f"{BASE_AUTH_URL}/accesstoken?grant_type=client_credentials"
    data = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}

    resp = requests.post(url, data=data)
    body = handle_response(resp, "Auth")

    token = body.get("access_token")
    if not token:
        raise Exception("Access token tidak ditemukan di response!")

    print(f"✅ Access Token didapat: {token[:40]}...")
    return token


# ─────────────────────────────────────────────
# STEP 2: Mencari Ihs Number Pasien & Dokter
# ─────────────────────────────────────────────
def get_patient_ihs(token: str) -> str:
    log("2a", f"Mencari IHS Number Pasien (NIK: {NIK_PASIEN})...")

    headers = {"Authorization": f"Bearer {token}"}
    url     = f"{BASE_FHIR_URL}/Patient"
    params  = {"identifier": f"https://fhir.kemkes.go.id/id/nik|{NIK_PASIEN}"}

    resp = requests.get(url, headers=headers, params=params)
    body = handle_response(resp, "Patient Search")

    entries = body.get("entry", [])
    if not entries:
        raise Exception(f"404 — Pasien dengan NIK {NIK_PASIEN} tidak ditemukan di sandbox.")

    ihs_id = entries[0]["resource"]["id"]
    nama   = entries[0]["resource"].get("name", [{}])[0].get("text", "N/A")
    print(f"✅ Pasien ditemukan: {nama}")
    print(f"   IHS Number: {ihs_id}")
    return ihs_id


def get_practitioner_ihs(token: str) -> str:
    log("2b", f"Mencari IHS Number Dokter (NIK: {NIK_DOKTER})...")

    headers = {"Authorization": f"Bearer {token}"}
    url     = f"{BASE_FHIR_URL}/Practitioner"
    params  = {"identifier": f"https://fhir.kemkes.go.id/id/nik|{NIK_DOKTER}"}

    resp = requests.get(url, headers=headers, params=params)
    body = handle_response(resp, "Practitioner Search")

    entries = body.get("entry", [])
    if not entries:
        raise Exception(f"404 — Dokter dengan NIK {NIK_DOKTER} tidak ditemukan di sandbox.")

    ihs_id = entries[0]["resource"]["id"]
    nama   = entries[0]["resource"].get("name", [{}])[0].get("text", "N/A")
    print(f"✅ Dokter ditemukan: {nama}")
    print(f"   IHS Number: {ihs_id}")
    return ihs_id


# ─────────────────────────────────────────────
# STEP 3: Membuat LOCATION
# ─────────────────────────────────────────────
def create_location(token: str) -> str:
    log("3", "Membuat resource Location (Ruang Poli Umum)...")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    # Menambahkan uuid supaya nama lokasi tidak dianggap duplikat oleh server
    unique_id = str(uuid.uuid4())[:8]

    payload = {
        "resourceType": "Location",
        "status": "active",
        "name": f"Ruang Poli Umum {unique_id}", # Ini yang diubah agar unik
        "description": "Ruang Poliklinik Umum Lantai 1",
        "mode": "instance",
        "physicalType": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/location-physical-type",
                "code":   "ro",
                "display": "Room"
            }]
        },
        "managingOrganization": {
            "reference": f"Organization/{ORG_ID}"
        }
    }

    resp = requests.post(f"{BASE_FHIR_URL}/Location", headers=headers, json=payload)
    body = handle_response(resp, "Location Create")

    location_id = body.get("id")
    print(f"✅ Location berhasil dibuat!")
    print(f"    Location ID: {location_id}")
    return location_id

# ─────────────────────────────────────────────
# STEP 4: Membuat ENCOUNTER
# ─────────────────────────────────────────────
def create_encounter(
    token: str,
    patient_ihs: str,
    practitioner_ihs: str,
    location_id: str
) -> dict:
    log("4", "Mendaftarkan Encounter (Kunjungan Pasien)...")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    # Timestamp ISO 8601 UTC
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    payload = {
        "resourceType": "Encounter",
        "status": "arrived",
        "identifier": [
            {
                "system": f"http://sys-ids.kemkes.go.id/encounter/{ORG_ID}",
                "value": f"REGISTRATION-{uuid.uuid4().hex[:8].upper()}" # Menjawab Rule 10117
            }
        ],
        "class": {
            "system":  "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code":    "AMB",
            "display": "ambulatory"
        },
        "subject": {
            "reference": f"Patient/{patient_ihs}",
            "display":   "Pasien"
        },
        "participant": [{
            "type": [{
                "coding": [{
                    "system":  "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                    "code":    "ATND",
                    "display": "attender"
                }]
            }],
            "individual": {
                "reference": f"Practitioner/{practitioner_ihs}",
                "display":   "Dokter"
            }
        }],
        "period": {
            "start": now_utc
        },
        "statusHistory": [
            {
                "status": "arrived",
                "period": {
                    "start": now_utc # Menjawab Rule 10122
                }
            }
        ],
        "location": [{
            "location": {
                "reference": f"Location/{location_id}",
                "display":   "Ruang Poli Umum"
            }
        }],
        "serviceProvider": {
            "reference": f"Organization/{ORG_ID}" # Pastikan ORG_ID di .env sudah benar (Rule 10124)
        }
    }

    resp = requests.post(f"{BASE_FHIR_URL}/Encounter", headers=headers, json=payload)
    body = handle_response(resp, "Encounter Create")

    encounter_id = body.get("id")
    print(f"✅ Encounter berhasil dibuat! Status: {resp.status_code} Created")
    print(f"    Encounter ID: {encounter_id}")
    print(f"    Timestamp   : {now_utc}")
    return body

# ─────────────────────────────────────────────
# MAIN FLOW
# ─────────────────────────────────────────────
def main():
    print("  SATUSEHAT PATIENT REGISTRATION FLOW")
    print("  Environment: SANDBOX/DEVELOPMENT")

    try:
        # Step 1
        token = get_access_token()

        # Step 2
        patient_ihs      = get_patient_ihs(token)
        practitioner_ihs = get_practitioner_ihs(token)

        # Step 3
        location_id = create_location(token)

        # Step 4
        encounter_response = create_encounter(
            token, patient_ihs, practitioner_ihs, location_id
        )

        # Summary
        print("  SEMUA LANGKAH BERHASIL!")
        print(f"\n  Patient IHS ID     : {patient_ihs}")
        print(f"  Practitioner IHS ID: {practitioner_ihs}")
        print(f"  Location ID        : {location_id}")
        print(f"  Encounter ID       : {encounter_response.get('id')}")

        # Simpan hasil ke file JSON
        result = {
            "patient_ihs_id":      patient_ihs,
            "practitioner_ihs_id": practitioner_ihs,
            "location_id":         location_id,
            "encounter_id":        encounter_response.get("id"),
            "encounter_response":  encounter_response,
        }
        with open("result.json", "w") as f:
            json.dump(result, f, indent=2)
        print("\n  📄 Full response disimpan ke result.json")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise


if __name__ == "__main__":
    main()
