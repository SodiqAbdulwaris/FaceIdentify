Computer Vision
Face detection
Face alignment
Face recognition
Face verification
Open-set recognition
Closed-set recognition
Face re-identification
Metric learning
Contrastive learning
Triplet loss
Self-supervised visual learning
Face quality assessment
Occlusion handling
Model Architectures
CNNs
Vision Transformers
Hybrid CNN/Transformer architectures
Siamese networks
Triplet networks
Metric-learning architectures
Identity Representation
Feature descriptors
Embeddings
Identity prototypes
Multiple-template recognition
Template aggregation
Prototype learning
Tracking
Multi-object tracking
Tracking-by-detection
Re-identification
Tracklets
Track association
Track stitching
Unknown Person Discovery
Clustering
DBSCAN
HDBSCAN
Agglomerative clustering
Online/incremental clustering
Video
FFmpeg
PyAV
OpenCV
NVDEC
hardware video decoding
frame sampling
scene-change detection
keyframes
Hardware Optimization
CUDA
cuDNN
TensorRT
ONNX Runtime
OpenVINO
CPU SIMD
multithreading
multiprocessing
asynchronous pipelines
pinned memory
GPU batching
zero-copy memory concepts
hardware video decoding
And specifically research:
CPU/GPU heterogeneous inference pipelines


One useful research checklist is:
- Face detection: RetinaFace, SCRFD, YOLO face variants, MTCNN; compare accuracy, small-face performance, multi-face throughput and GPU support.
- Face representation/recognition: ArcFace, FaceNet, AdaFace, MagFace, InsightFace ecosystem; understand metric learning, embeddings, cosine similarity, verification vs identification, open-set recognition and threshold calibration.
- Tracking: ByteTrack, DeepSORT, StrongSORT, BoT-SORT; especially the difference between generic object tracking and face-aware re-identification.
- Vector similarity/search: FAISS, HNSW, pgvector and approximate-nearest-neighbor search. We need to determine whether thousands of local identities even justify a separate vector index.
- Video processing: FFmpeg, OpenCV, PyAV; investigate seeking, decoding, keyframes, hardware decoding, chunking and frame sampling.
- Local GPU inference: PyTorch, ONNX Runtime, TensorRT and CUDA; especially model conversion and batching on an RTX 4070 Laptop GPU.
- Storage: PostgreSQL vs SQLite for a single-user local application, plus filesystem/object-like storage for video and face snapshots.
- Desktop application architecture: web UI + local FastAPI server versus Electron/Tauri/native shell. Don't decide yet.
- Clustering: DBSCAN/HDBSCAN/agglomerative clustering for discovering recurring unknown identities.
- Face quality assessment: blur, pose, occlusion, resolution and selecting the best representative observation from a track.
- Open-set recognition: this one is particularly important. Search specifically for open-set face identification, because our system must recognize known people while correctly rejecting unknown people.
- Continual/incremental learning: research it, but don't assume we need neural-network retraining. Updating identity prototypes/reference sets may be considerably safer and cheaper.
- Local natural-language querying: optional for later. We can implement deterministic structured queries before involving an LLM.
The concepts I'd spend the most research time on are:
open-set face recognition, face embeddings/metric learning, face clustering, face re-identification, multi-object tracking, threshold calibration, and continual identity learning.