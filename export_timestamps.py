Check task activity
block1 = np.nanmean(data[1200:1250,:,:], axis=0)
plt.figure()
plt.imshow(block1, cmap='gray')

Load in event timing
import pandas as pd

df = pd.read_csv("C:/Users/JoshB/Documents/Projects/resting_pilot/output/sub-02/ses-2/func/sub-02_ses-2_task-whisker_run-7_events.tsv", sep='\t')
Check onset time of imaging start
Take only puff timings
block_timing = df.loc[df['trial_type'] == 'block_start', ['trial_type', 'onset']]
Convert timing from seconds to frames - 10 Hz, offset by imaging start time
block_timing['onset_frame'] = np.ceil(block_timing['onset']*10 - 13)

Take task blocks from imaging data
onset_frame = block_timing['onset_frame'].to_numpy()
onset_frame = onset_frame.astype(int)
block_data = np.stack([
    data[start:start+50, :, :]
    for start in onset_frame
]) # block X frame X height X width

Average across all blocks and frames
Average across all blocks and frames
mean_block1 = np.nanmean(block_data, axis=(0,1))
plt.figure()
plt.imshow(mean_block1, cmap='magma')
plt.colorbar(orientation="vertical")
plt.axis('off')

mean_block2 = np.nanmean(block_data, axis=(0,1))
plt.figure()
plt.imshow(mean_block2, cmap='magma')
plt.colorbar(orientation="vertical")
plt.axis('off')

mean_blocks = (mean_block1 + mean_block2) / 2
plt.figure()
plt.imshow(mean_blocks, cmap='magma')
plt.colorbar(orientation="vertical")
plt.axis('off')