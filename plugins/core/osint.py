import os
import json
import httpx
import subprocess
import asyncio
from typing import Optional
import urllib.parse
from skills import Skill, SkillResult, registry
import osint_store

class DomainReconSkill(Skill):
    name = "domain_recon"
    description = "Lookup WHOIS registration, DNS records (A/MX/TXT), and historical subdomains for a domain."
    
    async def execute(self, domain: str, **kwargs) -> SkillResult:
        try:
            import whois
            import dns.resolver
        except ImportError:
            return SkillResult(False, "Missing dependencies. Please run: pip install python-whois dnspython")
            
        result_data = {"domain": domain}
        
        # WHOIS
        try:
            w = await asyncio.to_thread(whois.whois, domain)
            result_data["whois"] = {
                "registrar": w.registrar,
                "creation_date": str(w.creation_date),
                "name_servers": w.name_servers
            }
        except Exception as e:
            result_data["whois"] = f"Error: {e}"

        # DNS
        dns_records = {}
        for rtype in ["A", "MX", "TXT"]:
            try:
                answers = await asyncio.to_thread(dns.resolver.resolve, domain, rtype)
                dns_records[rtype] = [str(r) for r in answers]
            except Exception:
                pass
        result_data["dns"] = dns_records
        
        # crt.sh Subdomains
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                crt_url = f"https://crt.sh/?q={domain}&output=json"
                resp = await client.get(crt_url)
                if resp.status_code == 200:
                    certs = resp.json()
                    subdomains = set()
                    for c in certs:
                        if 'name_value' in c:
                            for name in c['name_value'].split('\n'):
                                subdomains.add(name.strip().lower())
                    result_data["subdomains"] = list(subdomains)[:50] # cap to 50
        except Exception as e:
            result_data["subdomains"] = f"Error fetching crt.sh: {e}"

        osint_store.log_evidence(self.name, domain, "Multiple sources (WHOIS, DNS, crt.sh)", result_data)
        return SkillResult(True, f"Completed domain recon for {domain}. Found {len(result_data.get('subdomains', []))} subdomains.", data=result_data)

registry.register(DomainReconSkill())


class ArchiveLookupSkill(Skill):
    name = "archive_lookup"
    description = "Check the Wayback Machine for archived snapshots of a specific URL."
    
    async def execute(self, url: str, **kwargs) -> SkillResult:
        api_url = f"https://archive.org/wayback/available?url={urllib.parse.quote(url)}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(api_url)
                if resp.status_code == 200:
                    data = resp.json()
                    snapshots = data.get("archived_snapshots", {})
                    closest = snapshots.get("closest")
                    if closest:
                        osint_store.log_evidence(self.name, url, api_url, data)
                        return SkillResult(True, f"Found snapshot from {closest.get('timestamp')}", data=closest)
                    
                    osint_store.log_evidence(self.name, url, api_url, {"status": "no snapshots found"})
                    return SkillResult(False, "No snapshots found for this URL.")
                else:
                    return SkillResult(False, f"Wayback API returned status {resp.status_code}")
        except Exception as e:
            return SkillResult(False, f"Wayback API error: {e}")

registry.register(ArchiveLookupSkill())


class CompanyLookupSkill(Skill):
    name = "company_lookup"
    description = "Search OpenCorporates and SEC EDGAR for company registration and filings."
    
    async def execute(self, name: str, jurisdiction: str = "", **kwargs) -> SkillResult:
        results = {"query": name}
        
        # OpenCorporates (requires API token — see https://api.opencorporates.com)
        oc_api_key = os.getenv("OPENCORPORATES_API_KEY")
        if oc_api_key:
            oc_url = f"https://api.opencorporates.com/v0.4.8/companies/search?q={urllib.parse.quote(name)}&api_token={oc_api_key}"
            if jurisdiction:
                oc_url += f"&jurisdiction_code={urllib.parse.quote(jurisdiction)}"
            
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(oc_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        companies = (data.get("results") or {}).get("companies") or []
                        results["opencorporates"] = [c.get("company") for c in companies[:5]]
                    else:
                        results["opencorporates_error"] = f"HTTP {resp.status_code}"
            except Exception as e:
                results["opencorporates_error"] = str(e)
        else:
            results["opencorporates_error"] = "Skipped — OPENCORPORATES_API_KEY not set in .env"
            
        # EDGAR full-text
        edgar_url = f"https://efts.sec.gov/LATEST/search-index?q={urllib.parse.quote(name)}"
        try:
            headers = {"User-Agent": "LIS-OSINT-Module contact@example.com"} # Replace with real contact info per SEC terms
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(edgar_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    hits = data.get("hits", {}).get("hits", [])
                    results["edgar"] = hits[:5]
        except Exception as e:
            results["edgar_error"] = str(e)
            
        osint_store.log_evidence(self.name, name, "OpenCorporates + SEC EDGAR", results)
        return SkillResult(True, f"Looked up company: {name}", data=results)

registry.register(CompanyLookupSkill())


class MetadataExtractSkill(Skill):
    name = "metadata_extract"
    description = "Extract metadata from a local file using exiftool (useful for images, PDFs, docs)."
    
    async def execute(self, file_path: str, **kwargs) -> SkillResult:
        if not os.path.exists(file_path):
            return SkillResult(False, f"File not found on local path: {file_path}")
            
        try:
            # -j for JSON output; capture stderr separately so warnings don't corrupt JSON
            proc_result = await asyncio.to_thread(
                subprocess.run, ['exiftool', '-j', file_path],
                capture_output=True
            )
            if proc_result.returncode != 0 and not proc_result.stdout.strip():
                return SkillResult(False, f"exiftool failed: {proc_result.stderr.decode(errors='replace')[:300]}")
            data = json.loads(proc_result.stdout)
            osint_store.log_evidence(self.name, file_path, "exiftool (local)", data)
            return SkillResult(True, f"Extracted metadata for {file_path}", data=data)
        except FileNotFoundError:
            return SkillResult(False, "exiftool is not installed or not on PATH. Please install it first.")
        except Exception as e:
            return SkillResult(False, f"Error extracting metadata: {e}")

registry.register(MetadataExtractSkill())


class UsernameSearchSkill(Skill):
    name = "username_search"
    description = "Check if a username exists across major platforms (GitHub, Reddit, X, etc)."
    
    async def execute(self, username: str, purpose: str = "", **kwargs) -> SkillResult:
        if not purpose or not purpose.strip():
            return SkillResult(False, "Missing purpose. Please ask the user why they need this username checked before proceeding.")
            
        safe_user = urllib.parse.quote(username, safe='')
        platforms = {
            "github": f"https://github.com/{safe_user}",
            "reddit": f"https://www.reddit.com/user/{safe_user}",
            "instagram": f"https://www.instagram.com/{safe_user}/",
            "twitter_x": f"https://x.com/{safe_user}"
        }
        
        results = {}
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False, headers=headers) as client:
                for site, url in platforms.items():
                    try:
                        resp = await client.head(url)
                        # Basic heuristic: 200 often means it exists, 404 means it doesn't.
                        # Note: Instagram/X sometimes block automated HEAD, this is just a best effort passive check.
                        if resp.status_code == 200:
                            results[site] = "likely exists (HTTP 200)"
                        elif resp.status_code == 404:
                            results[site] = "likely does not exist (HTTP 404)"
                        else:
                            results[site] = f"inconclusive (HTTP {resp.status_code})"
                    except Exception:
                        results[site] = "error checking"
                        
            osint_store.log_evidence(self.name, username, "Multiple Platforms (HTTP HEAD)", results, notes=f"Purpose: {purpose}")
            return SkillResult(True, f"Checked username: {username} across {len(platforms)} platforms.", data=results)
        except Exception as e:
            return SkillResult(False, f"Username check failed: {e}")

registry.register(UsernameSearchSkill())


class BreachCheckSkill(Skill):
    name = "breach_check"
    description = "Check if an email address has been compromised in data breaches via HaveIBeenPwned."
    
    async def execute(self, email: str, **kwargs) -> SkillResult:
        api_key = os.getenv("HIBP_API_KEY")
        if not api_key:
            return SkillResult(False, "Breach checking isn't configured — HIBP_API_KEY is missing.")
            
        url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{urllib.parse.quote(email)}?truncateResponse=false"
        headers = {
            "hibp-api-key": api_key,
            "user-agent": "LIS-OSINT-Module"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                
                if resp.status_code == 200:
                    data = resp.json()
                    osint_store.log_evidence(self.name, email, "HaveIBeenPwned API", data)
                    return SkillResult(True, f"Found {len(data)} breaches for this email.", data=data)
                elif resp.status_code == 404:
                    osint_store.log_evidence(self.name, email, "HaveIBeenPwned API", {"status": "clean"})
                    return SkillResult(True, "Email has not been found in any public breaches.")
                else:
                    return SkillResult(False, f"HIBP API returned status {resp.status_code}")
        except Exception as e:
            return SkillResult(False, f"Breach check failed: {e}")

registry.register(BreachCheckSkill())
