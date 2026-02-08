#!/usr/bin/env python3
"""
Analyze decision patterns from Google Sheet
Columns: C (overall_score), D (confidence), E (task_correctness_score), 
         G (causal_explainability_score), I (response_accuracy_score)
"""

import os

import gspread
import pandas as pd
from google.oauth2.credentials import Credentials

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "1J2FlN_tADPWx9HBnuXK68wNxC3yhfGMnB3czZOYLNSg")


def analyze_patterns():
    print("📊 Analyzing Decision Patterns from Google Sheet...")
    print("=" * 70)
    
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/drive.readonly'
    ]
    
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    gc = gspread.authorize(creds)
    
    print("   📡 Connecting to Google Sheets...")
    spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
    sheet = spreadsheet.sheet1
    
    print("   ⬇️ Downloading data...")
    all_values = sheet.get_all_values()
    
    headers = all_values[0]
    print(f"\n📋 Column mapping:")
    for i, h in enumerate(headers[:12]):
        col_letter = chr(65 + i)  # A, B, C, ...
        print(f"   {col_letter}: {h}")
    
    df = pd.DataFrame(all_values[1:], columns=headers)
    print(f"\n✅ Loaded {len(df)} rows")
    
    # Convert columns to numeric
    cols_to_analyze = ['overall_score', 'confidence', 'task_correctness_score', 
                       'causal_explainability_score', 'response_accuracy_score']
    
    for col in cols_to_analyze:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df['decision'] = df['decision'].astype(str).str.upper().str.strip()
    
    # Filter by decision types
    accept_df = df[df['decision'] == 'ACCEPT']
    review_df = df[df['decision'] == 'REVIEW']
    revise_df = df[df['decision'] == 'REVISE']
    
    print(f"\n📈 Statistics:")
    print(f"   Total rows: {len(df)}")
    print(f"   ACCEPT: {len(accept_df)}, REVIEW: {len(review_df)}, REVISE: {len(revise_df)}")
    
    # Analyze each decision type
    for decision_type, decision_df in [('ACCEPT', accept_df), ('REVIEW', review_df), ('REVISE', revise_df)]:
        print(f"\n{'='*70}")
        print(f"📊 {decision_type} Patterns:")
        print(f"{'='*70}")
        
        if decision_df.empty:
            print("   No data")
            continue
        
        print(f"\n   {'Column':<35} {'Min':>8} {'Max':>8} {'Mean':>8}")
        print(f"   {'-'*35} {'-'*8} {'-'*8} {'-'*8}")
        
        for col in cols_to_analyze:
            col_data = decision_df[col].dropna()
            if len(col_data) > 0:
                col_letter = chr(67 + cols_to_analyze.index(col))  # C, D, E, F, G...
                if col == 'causal_explainability_score':
                    col_letter = 'G'
                elif col == 'response_accuracy_score':
                    col_letter = 'I'
                print(f"   {col_letter}: {col:<32} {col_data.min():>8.2f} {col_data.max():>8.2f} {col_data.mean():>8.2f}")
    
    # Find correlation and suggested rules
    print(f"\n{'='*70}")
    print("🎯 SUGGESTED RULES FOR ACCEPT (từ data ACCEPT):")
    print(f"{'='*70}")
    
    if not accept_df.empty:
        for col in cols_to_analyze:
            col_data = accept_df[col].dropna()
            if len(col_data) > 0:
                min_val = col_data.min()
                pct_5 = col_data.quantile(0.05)  # 5th percentile (95% of data above this)
                print(f"   {col}: min={min_val:.2f}, 5th percentile={pct_5:.2f}")
    
    print(f"\n{'='*70}")
    print("📉 SUGGESTED RULES FOR REVISE (từ data REVISE):")
    print(f"{'='*70}")
    
    if not revise_df.empty:
        for col in cols_to_analyze:
            col_data = revise_df[col].dropna()
            if len(col_data) > 0:
                max_val = col_data.max()
                pct_95 = col_data.quantile(0.95)  # 95th percentile (95% of data below this)
                print(f"   {col}: max={max_val:.2f}, 95th percentile={pct_95:.2f}")
    
    # Cross analysis - find thresholds
    print(f"\n{'='*70}")
    print("🔍 CROSS ANALYSIS - Ngưỡng phân biệt ACCEPT vs REVISE:")
    print(f"{'='*70}")
    
    for col in cols_to_analyze:
        accept_min = accept_df[col].dropna().min() if len(accept_df[col].dropna()) > 0 else 0
        revise_max = revise_df[col].dropna().max() if len(revise_df[col].dropna()) > 0 else 0
        overlap = revise_max >= accept_min
        
        if overlap:
            # Find safe threshold
            accept_pct10 = accept_df[col].dropna().quantile(0.10) if len(accept_df[col].dropna()) > 0 else 0
            revise_pct90 = revise_df[col].dropna().quantile(0.90) if len(revise_df[col].dropna()) > 0 else 0
            print(f"   {col}:")
            print(f"      ACCEPT min: {accept_min:.2f}, 10th pct: {accept_pct10:.2f}")
            print(f"      REVISE max: {revise_max:.2f}, 90th pct: {revise_pct90:.2f}")
            print(f"      ⚠️ OVERLAP exists, safe ACCEPT threshold: >= {accept_pct10:.2f}")
        else:
            print(f"   {col}: No overlap (ACCEPT min={accept_min:.2f} > REVISE max={revise_max:.2f})")

if __name__ == "__main__":
    analyze_patterns()
