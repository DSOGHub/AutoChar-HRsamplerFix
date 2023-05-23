import modules.scripts as scripts
import gradio as gr
import os

from modules import images
from modules.processing import process_images, Processed
from modules.processing import Processed
from modules.shared import opts, cmd_opts, state
from modules import scripts_postprocessing, shared
from modules.processing import StableDiffusionProcessingImg2Img
from modules import processing, shared, sd_samplers, images, devices


# from scripts.postprocessing_uspscale import process, upscale


class Script(scripts.Script):

    # The title of the script. This is what will be displayed in the dropdown menu.
    def title(self):

        return "AutoChar Control Panel"

    # Determines when the script should be shown in the dropdown menu via the
    # returned value. As an example:
    # is_img2img is True if the current tab is img2img, and False if it is txt2img.
    # Thus, return is_img2img to only show the script on the img2img tab.

    # How the script's is displayed in the UI. See https://gradio.app/docs/#components
    # for the different UI components you can use and how to create them.
    # Most UI components can return a value, such as a boolean for a checkbox.
    # The returned values are passed to the run method as parameters.

    def ui(self, is_img2img):

        filtering = gr.Checkbox(True, label="Filtering function")

        strength = gr.Slider(minimum=0.0, maximum=1.0, step=0.05, value=0.5,
                             label="Strength of Filtering")
        scale_factor = gr.Slider(minimum=1.0, maximum=3.0, step=0.1, value=1.5,
                                 label="Img2img scale factor")

        with gr.Accordion('Denoising sliders', open=False):
            first_denoise = gr.Slider(minimum=0.0, maximum=1.0, step=0.05, value=0.55,
                                      label="First upscale denoising strength")
            second_denoise = gr.Slider(minimum=0.0, maximum=1.0, step=0.05, value=0.35,
                                       label="Second upscale denoising strength")
            face_denoise = gr.Slider(minimum=0.0, maximum=1.0, step=0.05, value=0.3,
                                     label="Face inpainting denoising strength")
            eyes_denoise = gr.Slider(minimum=0.0, maximum=1.0, step=0.05, value=0.4,
                                     label="Eyes inpainting denoising strength")

        options = gr.CheckboxGroup(label="Options", choices=['Automatic face inpaint', 'Automatic eyes inpaint'],
                                   elem_id=self.elem_id("options"))

        mid_inpainting = gr.Checkbox(False, label="Attempt mid-uspcale inpainting with chosen options ")

        ui_upscaler_1 = gr.Radio(
            ["Latent", "Nearest", "None"], label="Upscaler", value='Latent',
            elem_id=self.elem_id("ui_upscaler_1")
        )

        return [filtering, strength, ui_upscaler_1, first_denoise, second_denoise, face_denoise, eyes_denoise, options,
                mid_inpainting, scale_factor]

        # pp_upscale,pp_upscaler,pp_scale_factor]
        # with gr.Accordion('Post-processing', open=False):

        # pp_upscale = gr.Checkbox(True, label="Post-processing upscale")

        # pp_scale_factor = gr.Slider(minimum=1, maximum=3.0, step=0.1, value=2,
        #                         label="Post-proccessing scale factor")

        # pp_upscaler = gr.Dropdown(label='Upscaler for Post-proccessing', elem_id="pp_upscaler", choices=[x.name for x in shared.sd_upscalers], value=shared.sd_upscalers[0].name)

    # This is where the additional processing is implemented. The parameters include
    # self, the model object "p" (a StableDiffusionProcessing class, see
    # processing.py), and the parameters returned by the ui method.
    # Custom functions can be defined here, and additional libraries can be imported
    # to be used in processing. The return value should be a Processed object, which is
    # what is returned by the process_images method.

    def run(self, p, filtering, strength, ui_upscaler_1, first_denoise, second_denoise, face_denoise, eyes_denoise,
            options, mid_inpainting, scale_factor):  # ,pp_upscale,pp_upscaler,pp_scale_factor):
        initial_seed_and_info = [None, None]
        face_inpaint_flag = True if "Automatic face inpaint" in options else False
        eyes_inpaint_flag = True if "Automatic eyes inpaint" in options else False
        mid_face_flag = None
        mid_eyes_flag = None

        if mid_inpainting:
            mid_face_flag = face_inpaint_flag
            mid_eyes_flag = eyes_inpaint_flag

        print(options)
        print('filtering', filtering, 'strength', strength, 'ui_upscaler_1', ui_upscaler_1, 'face_inpaint_flag',
              face_inpaint_flag, 'eyes_inpaint_flag', eyes_inpaint_flag, 'scale_factor', scale_factor)
        # function which takes an image from the Processed object,
        # and the angle and two booleans indicating horizontal and
        # vertical flips from the UI, then returns the
        # image rotated and flipped accordingly
        from PIL import Image
        import cv2
        import numpy as np
        import torch
        import math
        final_image = None

        instance_img2img = StableDiffusionProcessingImg2Img()
        instance_img2img.outpath_samples = opts.outdir_txt2img_samples
        instance_inpaint = StableDiffusionProcessingImg2Img()
        instance_inpaint.outpath_samples = opts.outdir_txt2img_samples

        def closest(value, divider):
            return min((i for i in range(value - divider + 1, value + divider - 1)
                        if i % divider == 0),
                       key=lambda x: abs(x - value))

        def proportional_scaling(width, height, factor, threshold):

            step = 8  # 8 or 64
            # Calculate the aspect ratio of the image
            aspect_ratio = width / height

            # Scale the width and height by the given factor
            width = width * factor
            height = height * factor

            # Ensure that the resulting width and height are within the given threshold
            if width > threshold:
                # print(f" Proportional Scaling hit the limit: width {width} is larger than {threshold}")
                width = threshold
                height = width / aspect_ratio

            if height > threshold:
                # print(f" Proportional Scaling hit the limit: height {height} is larger than {threshold}")
                height = threshold
                width = height * aspect_ratio

            width = int(width)
            height = int(height)

            # Output height and width suitable for generation
            height = int(math.ceil(float(height) / float(step))) * step
            width = int(math.ceil(float(width) / float(step))) * step

            return (width, height)

        def enhance_image(image, strength):
            import numpy as np
            import cv2
            # Parameters:
            # image_path - path to image
            # strength - desired strength of filter, from 0 to 1,  default = 1
            # np_frame = np.array(image.images[0].convert("RGB"))
            image = np.array(image.images[0])
            # Detail enhance
            dst = cv2.detailEnhance(image, sigma_s=10, sigma_r=0.15)
            # sigma_s controls how much the image is smoothed - the larger its value,
            # the more smoothed the image gets, but it's also slower to compute.
            # sigma_r is important if you want to preserve edges while smoothing the image.
            # Small sigma_r results in only very similar colors to be averaged (i.e. smoothed), while colors that differ much will stay intact.
            # Sharpening kernel init
            kernel_sharpening = np.array([[-1, -1, -1],
                                          [-1, 9, -1],
                                          [-1, -1, -1]])
            # Sharpening
            dst2 = cv2.filter2D(image, -1, kernel_sharpening)
            # Blending detailed and sharpened images
            blended = cv2.addWeighted(dst, 0.6, dst2, 0.4, 0)
            # Denoising
            denoised = cv2.fastNlMeansDenoisingColored(blended, None, 5, 5, 7, 14)
            # Blending with the original
            denoised_blended = cv2.addWeighted(image, 1 - strength, denoised, strength, 0)
            print('Filtering complete')
            return Image.fromarray(denoised_blended)

        def mask_create(image):
            #  Regulating parameters
            face_resolution_scale = 2.5
            resolution_scale = 1.5
            mask_dilation = 1.5
            face_found = True
            rotate = False
            directory = os.path.dirname(__file__)
            image = np.array(image)

            # Load the model
            weights = os.path.join(directory, "face_detection_yunet_2022mar.onnx")
            face_detector = cv2.FaceDetectorYN_create(weights, "", (0, 0))

            # Face detection

            channels = 1 if len(image.shape) == 2 else image.shape[2]
            if channels == 1:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            if channels == 4:
                image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

            height, width, _ = image.shape
            face_detector.setInputSize((width, height))
            face_height_multiplier = 1

            _, faces = face_detector.detect(image)
            faces = faces if faces is not None else []

            # Checking if the face was found
            if len(faces) == 0:
                print("Face detection failed! Try more realistic picture.")
                face_found = False

            # Checking if the face box is horizontal
            if len(faces) == 1:
                face1 = faces[0]
                if face1[2] > face1[3]:
                    face_height_multiplier = 1.2
                    image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
                    rotate = True
                    height, width, _ = image.shape
                    face_detector.setInputSize((width, height))
                    _, faces = face_detector.detect(image)
                    print(faces)

            results = []
            for face in faces:
                face_width = face[2]
                # finding higher eye to measure eye y-coordinate difference
                if face[5] > face[7]:
                    higher_eye = (face[4], face[5])
                    lower_eye = (face[6], face[7])
                else:
                    higher_eye = (face[6], face[7])
                    lower_eye = (face[4], face[5])
                eye_y_dif = abs(int(higher_eye[1] / lower_eye[1]))
                eye_x_distance = abs(int(higher_eye[0] - lower_eye[0]))
                # if eye_x_distance >= 0.4 * face_width:
                if abs(face[4] - face[8]) >= 0.15 * face_width and abs(face[6] - face[8]) >= 0.15 * face_width:
                    # front or 3/4 view
                    eye_box_corner = (
                        int(face[4] - eye_x_distance * 0.55),
                        int(higher_eye[1] - eye_x_distance * 0.25 * (1.5 * eye_y_dif)))
                    face_height_multiplier = face_height_multiplier * 1.2
                    eye_y_dif_multiplier = 1.25
                else:
                    # profile view
                    eye_box_corner = (
                        int(face[4] - eye_x_distance),
                        int(higher_eye[1] - eye_x_distance * 0.45 * (1.4 * eye_y_dif)))
                    face_height_multiplier = face_height_multiplier * 1.3
                    eye_y_dif_multiplier = 1.5
                    if (face[4]) < (face[0] + 0.5 * face_width):  # left eye profile view
                        eye_box_corner = (
                            int(face[4] - eye_x_distance * 0.1),
                            int(higher_eye[1] - eye_x_distance * 0.45 * (1.65 * eye_y_dif)))
                    eye_x_distance = eye_x_distance * 1.2
                box = list(map(int, face[:4]))

                eye_box = [eye_box_corner[0], eye_box_corner[1], int(eye_x_distance * 2),
                           int((eye_x_distance * 0.8) * (eye_y_dif_multiplier * eye_y_dif))]
                color = (0, 0, 255)

                thickness = 2
                cv2.rectangle(image, box, color, thickness, cv2.LINE_AA)
                cv2.rectangle(image, eye_box, (0, 255, 255), thickness, cv2.LINE_AA)
                cv2.circle(image, eye_box_corner, 5, (0, 255, 255), -1, cv2.LINE_AA)

                if rotate:
                    image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
                mask1 = np.zeros(image.shape[:2], dtype="uint8")
                mask2 = np.zeros(image.shape[:2], dtype="uint8")
                box = [box[0], box[1], closest(int(box[2] * 1.25), 4),
                       closest(int(box[3] * face_height_multiplier), 4)]
                cv2.rectangle(mask1, box, 255, -1)
                cv2.rectangle(mask2, eye_box, 255, -1)
                inpaint_face_size = [closest(int(box[2] * face_resolution_scale), 4),
                                     closest(int(box[3] * face_resolution_scale), 4)]
                inpaint_eye_size = list(
                    [closest(int(eye_box[2] * resolution_scale), 4), closest(int(eye_box[3] * resolution_scale), 4)])
                while inpaint_face_size[0] < 384 or inpaint_face_size[1] < 384:
                    inpaint_face_size = list(
                        proportional_scaling(inpaint_face_size[0], inpaint_face_size[1], 1.1, 2048))
                    print('Face box too small! Initiating proportional_scaling')
                while inpaint_eye_size[0] < 384 or inpaint_eye_size[1] < 384:
                    print('Eye box too small! Initiating proportional_scaling')
                    inpaint_eye_size = list(proportional_scaling(inpaint_eye_size[0], inpaint_eye_size[1], 1.2, 2048))
                print("Resolution for face inpaint:\n" + str(inpaint_face_size), 'type:', type(inpaint_face_size))
                print("Resolution for eye inpaint:\n" + str(inpaint_eye_size), 'type:', type(inpaint_eye_size))
                results.append(
                    (Image.fromarray(mask1), Image.fromarray(mask2), inpaint_face_size, inpaint_eye_size, face_found))
            return results

        def text2img_hr(upscaler):

            # print the input
            print('txt2img+hr fix \n upscaler:', upscaler)

            # Change parameters
            p.enable_hr = True
            p.denoising_strength = first_denoise
            p.hr_scale = 1.2
            p.hr_upscaler = upscaler
            p.hr_second_pass_steps = 10

            # Start generation with high-res fix
            hr_output = process_images(p)

            # Write down the seed info for reproducibility
            initial_seed_and_info[0] = hr_output.seed
            initial_seed_and_info[1] = hr_output.info

            # Print confirmation
            print('HR fix complete')

            # Clear cache
            torch.cuda.empty_cache()

            return hr_output

        def img2img(init_image, scale_factor):

            # Print the input
            print(f"Input size for img2img: {init_image.images[0].size}")

            # Clear cache
            torch.cuda.empty_cache()

            # Change parameters
            instance_img2img.prompt = init_image.prompt
            instance_img2img.negative_prompt = init_image.negative_prompt
            instance_img2img.seed = init_image.seed
            instance_img2img.init_images = [init_image.images[0]]
            instance_img2img.denoising_strength = second_denoise
            instance_img2img.steps = 12

            # Change resolution so that it's surely dividable by 4
            instance_img2img.width = closest(int(scale_factor * init_image.images[0].width), 4)
            instance_img2img.height = closest(int(scale_factor * init_image.images[0].height), 4)

            # Print new resolution
            print('img2img resolution: ', instance_img2img.width, instance_img2img.height)

            # Run img2img
            img2img_output = process_images(instance_img2img)

            # Print confirmation
            print('img2mg finished!')

            # Clear cache
            torch.cuda.empty_cache()

            return img2img_output

        def inpaint(init_image,p_mask,w,h,denoise,rewrite_seed=False):

            # Change parameters
            if not rewrite_seed:
                instance_inpaint.seed = init_image.seed
            else:
                instance_inpaint.seed = random.randint(0,2147483647)
            instance_inpaint.prompt = init_image.prompt
            instance_inpaint.negative_prompt = init_image.negative_prompt
            instance_inpaint.seed = init_image.seed
            instance_inpaint.init_images = [init_image.images[0]]
            instance_inpaint.image_mask = p_mask
            instance_inpaint.mask_blur = int(w * 0.01)
            instance_inpaint.inpainting_fill = 1
            instance_inpaint.inpaint_full_res = True
            instance_inpaint.denoising_strength = denoise
            instance_inpaint.steps = 12
            instance_inpaint.width = w
            instance_inpaint.height = h

            # Print inpaint parameters
            print('Inpaint parameters: ', instance_inpaint.steps, instance_inpaint.width, instance_inpaint.height)

            # Run inpaint
            inpaint_output = process_images(instance_inpaint)

            # Clear cache
            torch.cuda.empty_cache()

            return inpaint_output

        hr_fix_output = text2img_hr(ui_upscaler_1)

        if filtering:
            hr_fix_output.images[0] = enhance_image(hr_fix_output, strength)

        if mid_face_flag:
            for (mask_face, mask_eyes, inpaint_face_size, inpaint_eye_size, face_found) in mask_create(
                    hr_fix_output.images[0]):
                if face_found:
                    print('Mid-uspcale face inpaint started: ')
                    mid_image_face_inpaint = inpaint(hr_fix_output, mask_face, inpaint_face_size[0],
                                                     inpaint_face_size[1],
                                                     face_denoise)
                    if mid_eyes_flag:
                        mask_face, mask_eyes, inpaint_face_size, inpaint_eye_size, face_found = mask_create(
                            mid_image_face_inpaint.images[0])
                        print('Mid-uspcale eyes inpaint started: ')
                        mid_image_eyes_inpaint = inpaint(mid_image_face_inpaint, mask_eyes, inpaint_eye_size[0],
                                                         inpaint_eye_size[1], eyes_denoise)
                        hr_fix_output.images[0] = mid_image_eyes_inpaint.images[0]
                    else:
                        hr_fix_output.images[0] = mid_image_face_inpaint.images[0]

        img2img_result = img2img(hr_fix_output, scale_factor)

        if face_inpaint_flag:
            for (mask_face, mask_eyes, inpaint_face_size, inpaint_eye_size, face_found) in mask_create(
                    img2img_result.images[0]):
                if face_found:
                    print('Face inpaint started: ')
                    image_face_inpaint = inpaint(img2img_result, mask_face, inpaint_face_size[0], inpaint_face_size[1],
                                                 face_denoise, True)
                    if eyes_inpaint_flag:
                        print('Eye inpaint started: ')
                        image_eyes_inpaint = inpaint(image_face_inpaint, mask_eyes, inpaint_eye_size[0],
                                                     inpaint_eye_size[1], eyes_denoise, True)
                        img2img_result = image_eyes_inpaint
                    else:
                        img2img_result = image_face_inpaint

        processed = img2img_result
        return processed
