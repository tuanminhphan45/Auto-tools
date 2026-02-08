#!/usr/bin/env python3
"""
Analyze decision patterns from Google Sheet
Find the relationship between columns D (overall_score), E (confidence) and B (decision)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

# Get Google Sheet ID from environment or hardcode
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "1J2FlN_tADPWx9HBnuXK68wNxC3yhfGMnB3czZOYLNSg")
from src.data_manager import DataManager


def analyze_patterns():
    print("📊 Analyzing Decision Patterns from Google Sheet...")
    print("=" * 60)
    
    # Load data from Google Sheet manually
    import gspread
    from google.oauth2.credentials import Credentials
    
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/drive.readonly'
    ]
    
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    gc = gspread.authorize(creds)
    
    print("   📡 Connecting to Google Sheets...")
    spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
    
    # List all worksheets
    print("\n📋 Available worksheets:")
    for ws in spreadsheet.worksheets():
        print(f"   - {ws.title}")
    
    # Try to get the first worksheet
    sheet = spreadsheet.sheet1
    print(f"\n   📂 Using worksheet: {sheet.title}")
    
    # Get all data
    print("   ⬇️ Downloading data...")
    all_values = sheet.get_all_values()
    
    if len(all_values) <= 1:
        print("❌ No data found!")
        return
    
    headers = all_values[0]
    print(f"\n📋 Column headers: {headers}")
    
    # Create DataFrame
    df = pd.DataFrame(all_values[1:], columns=headers)
    print(f"✅ Loaded {len(df)} rows")
    
    # Check data types and sample values
    print("\n📋 Sample data (first 5 rows):")
    print(df[['decision', 'overall_score', 'confidence']].head(10))
    
    # Convert to numeric
    df['overall_score'] = pd.to_numeric(df['overall_score'], errors='coerce')
    df['confidence'] = pd.to_numeric(df['confidence'], errors='coerce')
    df['decision'] = df['decision'].astype(str).str.upper().str.strip()
    
    # Filter rows where decision = ACCEPT
    accept_df = df[df['decision'] == 'ACCEPT']
    review_df = df[df['decision'] == 'REVIEW']
    revise_df = df[df['decision'] == 'REVISE']
    
    print(f"\n📈 Statistics:")
    print(f"   Total rows: {len(df)}")
    print(f"   ACCEPT rows: {len(accept_df)}")
    print(f"   REVIEW rows: {len(review_df)}")
    print(f"   REVISE rows: {len(revise_df)}")
    
    # Analyze REVISE patterns
    print("\n" + "=" * 60)
    print("📊 REVISE Decision Patterns (Column B = REVISE):")
    print("=" * 60)
    
    if not revise_df.empty:
        print(f"\n   Column D (overall_score):")
        print(f"      Min: {revise_df['overall_score'].min():.4f}")
        print(f"      Max: {revise_df['overall_score'].max():.4f}")
        print(f"      Mean: {revise_df['overall_score'].mean():.4f}")
        
        print(f"\n   Column E (confidence):")
        print(f"      Min: {revise_df['confidence'].min():.4f}")
        print(f"      Max: {revise_df['confidence'].max():.4f}")
        print(f"      Mean: {revise_df['confidence'].mean():.4f}")
        
        # Distribution by confidence levels
        print("\n   Distribution by Confidence (E) levels for REVISE:")
        for conf in sorted(revise_df['confidence'].dropna().unique()):
            subset = revise_df[revise_df['confidence'] == conf]
            if len(subset) > 0:
                print(f"      E = {conf}: {len(subset)} rows, D range: [{subset['overall_score'].min():.2f} - {subset['overall_score'].max():.2f}]")
    
    # Analyze ACCEPT patterns
    print("\n" + "=" * 60)
    print("📊 ACCEPT Decision Patterns (Column B = ACCEPT):")
    print("=" * 60)
    
    if not accept_df.empty:
        print(f"\n   Column D (overall_score):")
        print(f"      Min: {accept_df['overall_score'].min():.4f}")
        print(f"      Max: {accept_df['overall_score'].max():.4f}")
        print(f"      Mean: {accept_df['overall_score'].mean():.4f}")
        
        print(f"\n   Column E (confidence):")
        print(f"      Min: {accept_df['confidence'].min():.4f}")
        print(f"      Max: {accept_df['confidence'].max():.4f}")
        print(f"      Mean: {accept_df['confidence'].mean():.4f}")
        
        # Distribution by confidence levels
        print("\n   Distribution by Confidence (E) levels for ACCEPT:")
        for conf in sorted(accept_df['confidence'].dropna().unique()):
            subset = accept_df[accept_df['confidence'] == conf]
            if len(subset) > 0:
                print(f"      E = {conf}: {len(subset)} rows, D range: [{subset['overall_score'].min():.2f} - {subset['overall_score'].max():.2f}]")
    
    # Analyze REVIEW patterns
    print("\n" + "=" * 60)
    print("📊 REVIEW Decision Patterns (Column B = REVIEW):")
    print("=" * 60)
    
    if not review_df.empty:
        print(f"\n   Column D (overall_score):")
        print(f"      Min: {review_df['overall_score'].min():.4f}")
        print(f"      Max: {review_df['overall_score'].max():.4f}")
        print(f"      Mean: {review_df['overall_score'].mean():.4f}")
        
        print(f"\n   Column E (confidence):")
        print(f"      Min: {review_df['confidence'].min():.4f}")
        print(f"      Max: {review_df['confidence'].max():.4f}")
        print(f"      Mean: {review_df['confidence'].mean():.4f}")
        
        # Distribution by confidence levels
        print("\n   Distribution by Confidence (E) levels for REVIEW:")
        for conf in sorted(review_df['confidence'].dropna().unique()):
            subset = review_df[review_df['confidence'] == conf]
            if len(subset) > 0:
                print(f"      E = {conf}: {len(subset)} rows, D range: [{subset['overall_score'].min():.2f} - {subset['overall_score'].max():.2f}]")
    
    # Find suggested thresholds
    print("\n" + "=" * 60)
    print("🎯 SUGGESTED RULES for ACCEPT:")
    print("=" * 60)
    
    if not accept_df.empty:
        # Find the minimum D value for each E value in ACCEPT cases
        print("\n   Based on ACCEPT data, minimum D threshold for each E:")
        for conf in sorted(accept_df['confidence'].dropna().unique(), reverse=True):
            subset = accept_df[accept_df['confidence'] == conf]
            if len(subset) > 0:
                min_d = subset['overall_score'].min()
                print(f"      When E = {conf}: D >= {min_d:.2f} ({len(subset)} samples)")
        
        # Suggest a simple rule
        print("\n   📌 Suggested Decision Rule:")
        print("   if (E == 1 and D >= 0.75) or (E >= 0.7 and D >= 0.78):")
        print("       -> ACCEPT")
        print("   else:")
        print("       -> UNSURE")

if __name__ == "__main__":
    analyze_patterns()
