from datetime import datetime
# import pipeline_config

def get_badge_style(result: str) -> str:
    base_style = "border-radius:12px; padding:3px 10px; font-size:11px; font-weight:bold; display:inline-block; color:#ffffff; white-space:nowrap;"
    if result == "PASS": return base_style + " background-color:#1b5e20;"
    elif result in ["FAIL"]: return base_style + " background-color:#7f0000;"
    elif result == "TIMEOUT": return base_style + " background-color:#bf360c;"
    elif result == "WARNING": return base_style + " background-color:#ff6f00;"
    elif result == "EXECUTION_ERROR": return base_style + " background-color:#4a148c;"
    else: return base_style + " background-color:#546e7a;"

def get_category_badge_style(category: str) -> str:
    if not category or category == "-": return "display:none;"
    cat_lower = category.lower()
    base = "border-radius:4px; padding:2px 8px; font-size:11px; font-weight:bold; display:inline-block; white-space:nowrap;"
    if "multiple issues" in cat_lower: return base + " background-color:#e0f7fa; color:#006064; border:1px solid #80deea;"
    elif "cbt issue" in cat_lower and "suspected" not in cat_lower and "review" not in cat_lower: return base + " background-color:#fce4ec; color:#b71c1c; border:1px solid #ef9a9a;"
    elif "software issue" in cat_lower and "review" not in cat_lower: return base + " background-color:#fff3e0; color:#e65100; border:1px solid #ffb74d;"
    elif "suspected cbt issue" in cat_lower: return base + " background-color:#f3e5f5; color:#6a1b9a; border:1px solid #ce93d8;"
    elif "review required" in cat_lower: return base + " background-color:#e8eaf6; color:#283593; border:1px solid #9fa8da;"
    else: return base + " background-color:#f5f5f5; color:#616161; border:1px solid #e0e0e0;"

def build_email(builds: list[dict], kpis: dict, failure_analyses: dict, filters_used: dict) -> tuple[str, str]:
    now = datetime.now()
    to_date = now.strftime("%b %d, %Y")
    filter_summary = f"Lookback: {filters_used.get('lookback_hours', 24)}h"
    if filters_used.get("projects"): filter_summary += f" | Projects: {','.join(filters_used['projects'])}"
    
    subject = f"🔬 CBT Daily Intelligence Report | {filter_summary} | {kpis['passed']}✅ {kpis['failed']}❌"
    
    html = f"""
    <html><body style='font-family: Calibri, Arial, sans-serif; margin:0; padding:0; background-color:#ffffff;'>
    <div style='max-width:1300px; margin:0 auto; padding:20px;'>
        <table width="100%" cellpadding="20" cellspacing="0" border="0" style="background-color:#1a2744; color:#ffffff; font-family:Calibri, Arial, sans-serif;">
            <tr>
                <td align="left" valign="middle">
                    <h2 style="margin:0; font-size:24px; font-weight:bold; letter-spacing:0.5px;">CBT Daily Intelligence Report</h2>
                    <p style="margin:4px 0 0 0; font-size:14px; color:#e8f4fd;">Automotive Embedded Software &mdash; AI-Powered Fault Triage</p>
                </td>
                <td align="right" valign="middle" style="white-space:nowrap;">
                    <p style="margin:0; font-size:14px; font-weight:bold; color:#ffffff;">{filter_summary}</p>
                </td>
            </tr>
        </table>
        <div style="background:#0d1b3e; padding:4px 20px; font-size:11px; color:#90a4ae; font-family:monospace;">
          🤖 Powered by LLaMA 3 8B Local AI
        </div><br>
        
        <table width="100%" cellpadding="0" cellspacing="8" border="0" style="font-family:Calibri, Arial, sans-serif;">
            <tr>
                <td width="25%" align="center" style="background-color:#1a2744; padding:18px 10px; border-radius:8px;">
                    <div style="font-size:30px; font-weight:bold; color:#ffffff; margin-bottom:4px;">{kpis['total']}</div>
                    <div style="font-size:11px; color:#ffffff; text-transform:uppercase; font-weight:bold;">Total Builds</div>
                </td>
                <td width="25%" align="center" style="background-color:#1e7e34; padding:18px 10px; border-radius:8px;">
                    <div style="font-size:30px; font-weight:bold; color:#ffffff; margin-bottom:4px;">{kpis['passed']}</div>
                    <div style="font-size:11px; color:#ffffff; text-transform:uppercase; font-weight:bold;">Passed</div>
                </td>
                <td width="25%" align="center" style="background-color:#b71c1c; padding:18px 10px; border-radius:8px;">
                    <div style="font-size:30px; font-weight:bold; color:#ffffff; margin-bottom:4px;">{kpis['failed']}</div>
                    <div style="font-size:11px; color:#ffffff; text-transform:uppercase; font-weight:bold;">Failed</div>
                </td>
                <td width="25%" align="center" style="background-color:#e65100; padding:18px 10px; border-radius:8px;">
                    <div style="font-size:30px; font-weight:bold; color:#ffffff; margin-bottom:4px;">{kpis.get('warnings', 0)}</div>
                    <div style="font-size:11px; color:#ffffff; text-transform:uppercase; font-weight:bold;">Warnings</div>
                </td>
            </tr>
        </table><br>

        <h3 style="font-family:Calibri, Arial, sans-serif; color:#1a2744;">Detailed Build Matrix</h3>
        <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse:collapse; font-family:Calibri, Arial, sans-serif; font-size:12px; border:1px solid #d0d7de;">
            <thead>
                <tr style="background-color:#1a2744; color:#ffffff; font-weight:bold;">
                    <th style="border:1px solid #2f3e60; padding:8px 6px;" align="left">Build #</th>
                    <th style="border:1px solid #2f3e60; padding:8px 6px;" align="left">Project</th>
                    <th style="border:1px solid #2f3e60; padding:8px 6px;" align="left">Test Bench</th>
                    <th style="border:1px solid #2f3e60; padding:8px 6px;" align="center">Status</th>
                    <th style="border:1px solid #2f3e60; padding:8px 6px;" align="left">AI Root Cause Analysis</th>
                </tr>
            </thead>
            <tbody>
    """
    sorted_builds = sorted(builds, key=lambda b: 0 if b.get("end_result") in ["FAIL","TIMEOUT","EXECUTION_ERROR"] else 1)
    for b in sorted_builds:
        bnum = b.get("build_number", "N/A")
        res = b.get("end_result", "N/A")
        analysis_data = failure_analyses.get(str(bnum), {})
        category = analysis_data.get("category", "-") if isinstance(analysis_data, dict) else "-"
        analysis_text = analysis_data.get("text", "") if isinstance(analysis_data, dict) else ""
        
        bg_color = "#ffffff"
        if res == "PASS": bg_color = "#f1f8e9"
        elif res == "WARNING": bg_color = "#fff8e1"
        elif res in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]:
            cat_lower = category.lower()
            if "multiple issues" in cat_lower: bg_color = "#e0f7fa"
            elif "cbt issue" in cat_lower and "suspected" not in cat_lower and "review" not in cat_lower: bg_color = "#fce4ec"
            elif "software issue" in cat_lower and "review" not in cat_lower: bg_color = "#fff3e0"
            elif "suspected cbt issue" in cat_lower: bg_color = "#f3e5f5"
            elif "review required" in cat_lower: bg_color = "#e8eaf6"
            else: bg_color = "#fff5f5"
            
        html += f"""
        <tr style="background-color:{bg_color};">
            <td style="border:1px solid #d0d7de; padding:6px; font-weight:bold;">{bnum}</td>
            <td style="border:1px solid #d0d7de; padding:6px;">{b.get('project', 'N/A')}</td>
            <td style="border:1px solid #d0d7de; padding:6px;">{b.get('test_bench', 'N/A')}</td>
            <td style="border:1px solid #d0d7de; padding:6px;" align="center"><span style="{get_badge_style(res)}">{res}</span></td>
            <td style="border:1px solid #d0d7de; padding:6px;">
                <div style="margin-bottom:4px;"><span style="{get_category_badge_style(category)}">{category}</span></div>
                <div style="font-size:11px; color:#444;">{analysis_text}</div>
            </td>
        </tr>
        """
    
    html += f"""
            </tbody>
        </table><br><br>
        <hr style="border:0; border-top:1px solid #dddddd;">
        <div style="font-size:12px; color:#a8b4c9;">Generated at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} by CBT Intelligence System</div>
    </div></body></html>
    """
    return html, subject