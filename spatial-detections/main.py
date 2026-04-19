import os
import sys
import time

import depthai as dai
from depthai_nodes.node import ApplyColormap

# Allow importing app/ from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import broadcast, set_navigation_service, start_in_background  # noqa: E402
from app.models import Detection3D  # noqa: E402
from app.navigation_service import NavigationService  # noqa: E402

from utils.arguments import initialize_argparser
from utils.annotation_node import AnnotationNode
from utils.assistive_audio_node import AssistiveAudioNode
from utils.detection_sink_node import DetectionSinkNode

_, args = initialize_argparser()

# Start WebSocket server before pipeline so clients can connect early
_nav_service = NavigationService()
set_navigation_service(_nav_service)
start_in_background()

visualizer = dai.RemoteConnection(httpPort=8082)
device = dai.Device(dai.DeviceInfo(args.device)) if args.device else dai.Device()
platform = device.getPlatform().name
print(f"Platform: {platform}")

frame_type = (
    dai.ImgFrame.Type.BGR888p if platform == "RVC2" else dai.ImgFrame.Type.BGR888i
)

if args.fps_limit is None:
    args.fps_limit = 20 if platform == "RVC2" else 30
    print(
        f"\nFPS limit set to {args.fps_limit} for {platform} platform. If you want to set a custom FPS limit, use the --fps_limit flag.\n"
    )

available_cameras = device.getConnectedCameras()
if len(available_cameras) < 3:
    raise ValueError(
        "Device must have 3 cameras (color, left and right) in order to run this example."
    )

with dai.Pipeline(device) as pipeline:
    print("Creating pipeline...")

    # detection model
    det_model_description = dai.NNModelDescription.fromYamlFile(
        f"yolov10_nano_r2_coco.{platform}.yaml"
    )
    if det_model_description.model != args.model:
        det_model_description = dai.NNModelDescription(args.model, platform=platform)
    det_model_nn_archive = dai.NNArchive(dai.getModelFromZoo(det_model_description))
    classes = det_model_nn_archive.getConfig().model.heads[0].metadata.classes
    nn_size = det_model_nn_archive.getInputSize()

    # camera input
    cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)

    left_cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_B)
    right_cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_C)
    stereo = pipeline.create(dai.node.StereoDepth).build(
        left=left_cam.requestOutput(nn_size, fps=args.fps_limit),
        right=right_cam.requestOutput(nn_size, fps=args.fps_limit),
        presetMode=dai.node.StereoDepth.PresetMode.HIGH_DETAIL,
    )
    stereo.initialConfig.postProcessing.temporalFilter.enable = True
    stereo.initialConfig.postProcessing.temporalFilter.delta = 100
    stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
    if platform == "RVC2":
        stereo.setOutputSize(*nn_size)
    stereo.setLeftRightCheck(True)
    stereo.setRectification(True)

    nn = pipeline.create(dai.node.SpatialDetectionNetwork).build(
        input=cam,
        stereo=stereo,
        nnArchive=det_model_nn_archive,
        fps=float(args.fps_limit),
    )
    if platform == "RVC2":
        nn.setNNArchive(
            det_model_nn_archive, numShaves=7
        )  # TODO: change to numShaves=4 if running on OAK-D Lite
    nn.setBoundingBoxScaleFactor(0.7)

    # annotation
    annotation_node = pipeline.create(AnnotationNode).build(
        input_detections=nn.out, depth=stereo.depth, labels=classes
    )

    # assistive audio — depth-based obstacle detection
    assistive_audio_node = pipeline.create(AssistiveAudioNode).build(
        depth=stereo.depth, interval=args.interval
    )

    def _on_command(command: str, zone_metrics_map: dict) -> None:
        broadcast(_nav_service.format_obstacle_message(command, zone_metrics_map))

    assistive_audio_node.on_command = _on_command

    def _on_detections(detections) -> None:
        det_list = []
        for d in detections:
            label = classes[d.label] if d.label < len(classes) else str(d.label)
            det_list.append(Detection3D(
                track_id=None,
                label=label,
                confidence=d.confidence,
                x1=int(d.xmin * nn_size[0]),
                y1=int(d.ymin * nn_size[1]),
                x2=int(d.xmax * nn_size[0]),
                y2=int(d.ymax * nn_size[1]),
                x_mm=d.spatialCoordinates.x,
                y_mm=d.spatialCoordinates.y,
                z_mm=d.spatialCoordinates.z,
                timestamp=time.time(),
            ))
        _nav_service.update_detections(det_list)

    detection_sink = pipeline.create(DetectionSinkNode).build(
        detections=nn.out, on_detections=_on_detections
    )

    apply_colormap = pipeline.create(ApplyColormap).build(stereo.depth)

    # video encoding
    cam_nv12 = cam.requestOutput(
        size=nn_size,
        fps=args.fps_limit,
        type=dai.ImgFrame.Type.NV12,
    )
    video_encoder = pipeline.create(dai.node.VideoEncoder)
    video_encoder.setMaxOutputFrameSize(nn_size[0] * nn_size[1] * 3)
    video_encoder.setDefaultProfilePreset(
        args.fps_limit, dai.VideoEncoderProperties.Profile.H264_MAIN
    )
    cam_nv12.link(video_encoder.input)

    # depth colormap encoding
    depth_encoder_manip = pipeline.create(dai.node.ImageManip)
    depth_encoder_manip.setMaxOutputFrameSize(nn_size[0] * nn_size[1] * 3)
    depth_encoder_manip.initialConfig.setOutputSize(*nn_size)
    depth_encoder_manip.initialConfig.setFrameType(dai.ImgFrame.Type.NV12)
    apply_colormap.out.link(depth_encoder_manip.inputImage)

    depth_encoder = pipeline.create(dai.node.VideoEncoder)
    depth_encoder.setMaxOutputFrameSize(nn_size[0] * nn_size[1] * 3)
    depth_encoder.setDefaultProfilePreset(
        args.fps_limit, dai.VideoEncoderProperties.Profile.H264_MAIN
    )
    depth_encoder_manip.out.link(depth_encoder.input)

    # visualization
    visualizer.addTopic("Camera", video_encoder.out)
    visualizer.addTopic("Detections", annotation_node.out_annotations)
    visualizer.addTopic("Depth", depth_encoder.out)

    print("Pipeline created.")

    pipeline.start()
    visualizer.registerPipeline(pipeline)

    while pipeline.isRunning():
        key = visualizer.waitKey(1)
        if key == ord("q"):
            print("Got q key. Exiting...")
            break
            