import pandas as pd
import numpy as np
import sys
import os # Ensure OS is imported

def analyze_csv(csv_path):
    print(f"Python script CWD: {os.getcwd()}") # New debug line
    print(f"Looking for CSV at: {csv_path}") # New debug line
    print(f"CSV exists: {os.path.exists(csv_path)}") # New debug line
    try:
        # Read the CSV file
        df = pd.read_csv(csv_path)

        # Identify the badness column (assuming 'BadnessAllChars')
        badness_column = 'Badness'

        if badness_column not in df.columns:
            print(f"Error: Column '{badness_column}' not found in the CSV.")
            print(f"Available columns: {df.columns.tolist()}")
            return

        # Drop rows where badness score might be NaN, if any
        df = df.dropna(subset=[badness_column])
        
        # Ensure the badness column is numeric.
        # Attempt to extract numbers if they are in "Some(number)" format, as seen in logs.
        if df[badness_column].dtype == 'object':
            # This regex handles "Some(value)" and also plain numbers
            df[badness_column] = df[badness_column].astype(str).str.extract(r'(?:Some\()?(-?\d+\.\d+e?-?\d*|-?\d+)(?:\))?')
            df[badness_column] = pd.to_numeric(df[badness_column], errors='coerce')
        elif not pd.api.types.is_numeric_dtype(df[badness_column]):
             df[badness_column] = pd.to_numeric(df[badness_column], errors='coerce')

        df = df.dropna(subset=[badness_column]) # Drop NaNs that might result from extraction/conversion

        if df[badness_column].empty:
            print(f"No valid numeric data found in column '{badness_column}' after processing.")
            return

        min_score = df[badness_column].min()
        max_score = df[badness_column].max()
        
        print(f"Minimum badness score: {min_score}")
        print(f"Maximum badness score: {max_score}")

        # Create bins with a step of 0.1
        # np.arange might have precision issues with floats for the upper limit.
        start_val = np.floor(min_score * 10) / 10
        # Add a small epsilon to the end to ensure the max value is included in the range for arange
        end_val = np.ceil(max_score * 10) / 10 + 1e-9 
        
        bins = np.arange(start_val, end_val + 0.1, 0.1) # Add 0.1 to end_val because arange is exclusive of the endpoint for the full range

        # Refine bins to ensure they are unique and sorted, and at least two edges exist
        bins = sorted(list(set(np.round(bins, 2)))) # Round to handle potential float precision artifacts
        
        if len(bins) < 2:
            if not df[badness_column].empty:
                print(f"Warning: Not enough distinct values or too narrow range to create multiple bins with step 0.1. Min: {min_score}, Max: {max_score}")
                # Fallback: create a few bins over the actual data range if it's very small
                if min_score == max_score:
                    bins = [min_score - 0.05, max_score + 0.05]
                else:
                    bins = np.linspace(min_score, max_score, num=5) # Create 4 bins (5 edges)
                print(f"Using fallback bins: {bins}")
            else:
                print("No data to bin.")
                return
        
        # Remove duplicates again after potential linspace fallback
        bins = sorted(list(set(np.round(bins, 2))))
        if len(bins) <2 and not df[badness_column].empty:
             bins = [df[badness_column].min() -0.05, df[badness_column].max() + 0.05]


        score_distribution = pd.cut(df[badness_column], bins=bins, include_lowest=True, right=False)
        counts = score_distribution.value_counts().sort_index()

        print("\nDistribution of files by badness score (step 0.1 or fallback):")
        print(counts)
        
        # Check if all data was binned
        if counts.sum() != len(df[badness_column]):
            print(f"Warning: {len(df[badness_column]) - counts.sum()} scores ({len(df[badness_column])} total) were outside the defined bins. This might indicate an issue with bin generation.")
            print(f"Min score processed: {min_score}, Max score processed: {max_score}")
            print(f"Bins used: {bins}")
            # Show unbinned values
            # unbinned_indices = df[badness_column][~df[badness_column].isin(score_distribution.dropna())].index
            # print(f"Sample of unbinned scores: {df[badness_column][unbinned_indices].head()}")

        # --- New analysis for Greek Percentage for low badness scores ---
        print("\n--- Analysis of Greek Percentage for files with Badness < 0.1 ---")
        low_badness_df = df[(df[badness_column] >= 0.0) & (df[badness_column] < 0.1)].copy() # Use .copy() to avoid SettingWithCopyWarning

        if low_badness_df.empty:
            print("No files found with badness score between 0.0 and 0.1.")
        else:
            greek_percentage_col = 'Greek Percentage'
            if greek_percentage_col not in low_badness_df.columns:
                print(f"Error: Column '{greek_percentage_col}' not found.")
            else:
                # Ensure 'Greek Percentage' is numeric (0.0 to 1.0)
                # Handle cases like "75.5%" or plain numbers (assuming 0-100 if > 1, else 0-1)
                if low_badness_df[greek_percentage_col].dtype == 'object':
                    low_badness_df.loc[:, greek_percentage_col] = low_badness_df[greek_percentage_col].astype(str).str.rstrip('%')
                    low_badness_df.loc[:, greek_percentage_col] = pd.to_numeric(low_badness_df[greek_percentage_col], errors='coerce')
                    # If values are > 1 after stripping %, assume they were 0-100 scale
                    if not low_badness_df[low_badness_df[greek_percentage_col] > 1].empty:
                         low_badness_df.loc[low_badness_df[greek_percentage_col] > 1, greek_percentage_col] = low_badness_df.loc[low_badness_df[greek_percentage_col] > 1, greek_percentage_col] / 100.0
                elif pd.api.types.is_numeric_dtype(low_badness_df[greek_percentage_col]):
                    # If numeric and consistently > 1 (e.g. 75.5 for 75.5%), convert to 0-1 scale
                    # This is a heuristic; it's better if the data is consistent
                    if not low_badness_df[low_badness_df[greek_percentage_col] > 1.0].empty and low_badness_df[greek_percentage_col].max() <=100.0 : # Check if it looks like 0-100 scale
                        low_badness_df.loc[:, greek_percentage_col] = low_badness_df[greek_percentage_col] / 100.0
                else: # Some other non-numeric type, try to coerce
                    low_badness_df.loc[:, greek_percentage_col] = pd.to_numeric(low_badness_df[greek_percentage_col], errors='coerce')


                low_badness_df.dropna(subset=[greek_percentage_col], inplace=True)
                
                # Ensure all values are within [0, 1] after conversion, clamp if necessary due to precision
                low_badness_df.loc[:, greek_percentage_col] = low_badness_df[greek_percentage_col].clip(0.0, 1.0)


                if low_badness_df[greek_percentage_col].empty:
                    print(f"No valid numeric data found for '{greek_percentage_col}' in the low badness subset.")
                else:
                    min_greek_perc = low_badness_df[greek_percentage_col].min()
                    max_greek_perc = low_badness_df[greek_percentage_col].max()
                    print(f"Subset (Badness < 0.1): Min Greek Percentage: {min_greek_perc:.3f}, Max Greek Percentage: {max_greek_perc:.3f}")

                    # Bins for percentage (0.0 to 1.0, step 0.1)
                    # Adding a small epsilon to 1.0 for the upper limit of arange if data can be exactly 1.0
                    percentage_bins = np.arange(0.0, 1.0 + 1e-9 + 0.1, 0.1) 
                    percentage_bins = sorted(list(set(np.round(percentage_bins, 2))))


                    if len(percentage_bins) < 2:
                        if not low_badness_df[greek_percentage_col].empty:
                             percentage_bins = [low_badness_df[greek_percentage_col].min() -0.05, low_badness_df[greek_percentage_col].max() + 0.05]
                             percentage_bins = [max(0,bins[0]), min(1,bins[1])] # clamp to 0-1
                        else:
                             percentage_bins = [0,0.1]


                        percentage_bins = sorted(list(set(np.round(percentage_bins, 2))))
                        if len(percentage_bins) < 2: # Still an issue
                            percentage_bins = [0,1.0]


                    greek_dist = pd.cut(low_badness_df[greek_percentage_col], bins=percentage_bins, include_lowest=True, right=False)
                    greek_counts = greek_dist.value_counts().sort_index()

                    print(f"\nDistribution of '{greek_percentage_col}' for files with Badness < 0.1 (Total: {len(low_badness_df)} files):")
                    print(greek_counts)
                    
                    if greek_counts.sum() != len(low_badness_df[greek_percentage_col]):
                        print(f"Warning: {len(low_badness_df[greek_percentage_col]) - greek_counts.sum()} Greek Percentage scores were outside the defined bins for the subset.")

                    # --- Count of files with Badness < 0.1 AND Greek Percentage >= 0.7 ---
                    count_low_badness_high_greek = low_badness_df[low_badness_df[greek_percentage_col] >= 0.7].shape[0]
                    print(f"\nNumber of files with Badness < 0.1 AND Greek Percentage >= 0.7: {count_low_badness_high_greek}")
                    total_files = df.shape[0]
                    if total_files > 0:
                        percentage_of_total = (count_low_badness_high_greek / total_files) * 100
                        print(f"This is {percentage_of_total:.2f}% of the total {total_files} files processed in the CSV.")

    except FileNotFoundError:
        print(f"Error: The file {csv_path} was not found.")
    except pd.errors.EmptyDataError:
        print(f"Error: The file {csv_path} is empty.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        analyze_csv(file_path)
    else:
        print("Please provide the CSV file path as a command-line argument.")
        # Default path for direct execution if needed, but prefer command-line argument
        # analyze_csv("/mnt/data/AI4Deliberation/ΦΕΚ/nomoi/pipeline_report_mu_fix.csv") 