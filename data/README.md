### Data Structure
By default, data is not committed to the repository, with the exception of the prepared training data. However, when executing the project scripts, data will generated, stored and processed locally using the following overall structure:

```
 📦data
  ┣ 📂<location>
  ┃ ┣ 📂final
  ┃ ┣ 📂processed
  ┃ ┃ ┣ 📂chips
  ┃ ┃ ┃ ┣ 📂temporal_mean_imgs
  ┃ ┃ ┣ 📂predictions
  ┃ ┃ ┣ 📂training
  ┃ ┗ 📂raw
  ┃ ┃ ┣ 📂s2_images
  ┃ ┃ ┗ 📜<location>.osm.pbf
  ┣ 📂preprepared_training_data
  ┃ ┣ 📜nairobi2_training_features.csv
  ┃ ┗ 📜nairobi_training_features.csv
```

Where `<location>` is the string representation of the location of interest. Generation of the folders will be generated automatically during the appropriate stage of execution.
