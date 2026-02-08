from src.data_manager import DataManager
dm = DataManager(
    file_path='nereid-evals.xlsx',
    google_sheet_id='1J2FlN_tADPWx9HBnuXK68wNxC3yhfGMnB3czZOYLNSg',
    credentials_file='oauth_credentials.json'
)
if dm.df is not None:
    print(f'\n📊 TOTAL RECORDS: {len(dm.df)}')
    print(f'📋 COLUMNS: {list(dm.df.columns)}')
else:
    print('❌ Failed to load data')
