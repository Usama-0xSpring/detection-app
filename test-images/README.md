# Test images

Sample photos for trying the detector. The default YOLOv8n model knows 80 COCO
objects (people, cars, animals, furniture...), **not signatures**.

| File | What the model finds (approx.) | Source |
|---|---|---|
| bus.jpg | person x4, bus | Ultralytics sample asset |
| zidane.jpg | person x2, tie | Ultralytics sample asset |
| cats-on-couch.jpg | cat x2, remote x2, couch | COCO val2017 #39769 |
| living-room.jpg | chair, tv, vase, clock, fridge, person | COCO val2017 #139 |
| bear.jpg | bear | COCO val2017 #285 |
| bedroom.jpg | bed, chair, book, potted plant, bottle | COCO val2017 #632 |
| stop-sign.jpg | stop sign x2 | COCO val2017 #724 |
| teddy-bears.jpg | teddy bear x3 | COCO val2017 #776 |
| skier.jpg | person, skis | COCO val2017 #785 |
| tennis-crowd.jpg | person x12, tennis racket | COCO val2017 #1000 |

## Licenses and credits

- **COCO images** (downloaded from `images.cocodataset.org/val2017/<id>.jpg`) come
  from Flickr. The COCO dataset publishes them under various Creative Commons
  licenses **chosen by each photographer**; some require attribution and some
  restrict commercial use or derivatives. Per-image license and author are listed
  at https://cocodataset.org/#explore (search by image id). Use these images for
  teaching and testing only, and check the license of an image before reusing it
  elsewhere.
- **bus.jpg / zidane.jpg** are sample assets shipped with the Ultralytics package
  (AGPL-3.0 project).
- Numbers above come from one run of the yolov8n model at 25% confidence and may
  differ slightly with another model.
