# Short Video Generation Instructions

## Video Size and Guest Information

- Short video size: **1080 x 1920**.
- The video already contains the guest name and phone number. When creating a short video, preserve the same guest name and phone number.
- Other content should use the normal size.
- The video must match the selected output size and fit within the provided measurements.
- The final output video must be generated correctly.

## Development Notes

```text
python -m streamlit run auto_shorts/streamlit_app.py
```

From the folder structure, the most suspicious files are:

- `export.py` - first file to check
- `clip.py`
- `runner.py`
- Possibly `transitions.py`

The final output should be:

- 1080 x 1920
- 9:16 vertical
- MP4
- H.264 (`libx264`) or a compatible configured codec
- AAC audio
- Suitable for YouTube Shorts

Changes included:

- Guest video fits inside the 1080 x 1920 YouTube Shorts frame.
- More of the guest's body and surroundings remain visible.
- No aggressive zoom or crop in the single-frame vertical layout.
- Empty areas are padded with black instead of cutting the guest.
- The reference template also uses `fit_mode='pad'`.
- Face-tracking coordinates are corrected if face tracking is enabled later.
- Python syntax check passed successfully.

## PowerShell or Terminal Path Troubleshooting

### Step 1 - Check Whether the Settings Change Applied

Reload or restart VS Code after adding:

```json
"terminal.integrated.shellIntegration.enabled": false
```

Settings like this sometimes need a full window reload. Use:

`Ctrl+Shift+P` -> **Developer: Reload Window**

### Step 2 - Force a No-Profile Terminal Directly in VS Code

Instead of relying on default profile settings, explicitly create one:

`Ctrl+Shift+P` -> **Terminal: Create New Terminal (With Profile)**

If a no-profile option is not available, click the dropdown arrow next to the plus button, select **Select Default Profile**, and temporarily choose **Command Prompt** as a test.

---

## Existing Application

The program has already been developed. Implement the required changes within the existing application based on the requirements below.

# Dynamic Short Video Generation Platform - Requirement Enhancement

## Objective

Build a dynamic short video generation system that creates professional short videos from a long video source. The entire screen layout, positioning, and video composition should be configurable through the UI without hardcoded values.

The system should primarily focus on generating short videos from a long video and allow users to design the layout dynamically before rendering the final output.

## UI/UX, Dashboard, and Branding Enhancements

In addition to video generation functionality, the application should have a modern, professional, and user-friendly web design.

### Dashboard Requirements

The application should include a professional dashboard with:

- Clean and responsive UI design.
- Modern layout following current UX best practices.
- Easy navigation between modules.
- Mobile, tablet, and desktop compatibility.
- Professional color themes and branding support.

### Navigation Menu

A structured navigation menu should be available, preferably on the left side, containing:

- Dashboard
- Video Upload
- Segment Management
- Layout Designer
- Preview
- Video Rendering
- Generated Videos
- Templates
- Settings

### Header Section

The top header should include:

- Application name
- User profile information
- Notifications
- Search option (optional)

### Logo Placement

The company or application logo should be displayed in a prominent position, preferably:

- Top-right corner of the application, or
- Top-left corner beside the application name

The logo should be configurable from the Settings page and should automatically appear across all screens based on branding settings.

### Dynamic Layout Builder UI

The Layout Designer should provide a drag-and-drop experience where users can:

- Move video frames dynamically.
- Resize video frames.
- Position titles anywhere on the canvas.
- Position guest names anywhere on the canvas.
- Place images, logos, and watermarks dynamically.
- Configure fonts, colors, alignment, and spacing.

### Preview Dashboard

Before rendering, users should see a professional preview screen showing:

- Selected video segment.
- Layout configuration.
- Video frame location.
- Title placement.
- Guest details placement.
- Logo placement.
- Thumbnail-style preview.

This preview should closely represent the final output, enabling users to validate the design before rendering.

### Overall Objective

The entire application should feel like a professional video editing and short-content creation platform, with a highly dynamic and configurable UI. Users should be able to control all design elements from the dashboard and generate short videos without requiring code changes or hardcoded layouts. The system should prioritize flexibility, usability, branding, and a professional user experience.

## Functional Requirements

### 1. Long Video Input

The user will upload a long video, for example, a 15-minute video.

The system should:

- Accept long video uploads.
- Display video information.
- Allow users to create multiple short videos from the same source video.
- Support extraction of specific segments from the long video.

Example:

- Long video duration: 15 minutes
- Short Video 1: 00:01:30 - 00:04:30
- Short Video 2: 00:05:00 - 00:08:00
- Short Video 3: 00:09:00 - 00:12:00

Each short video should allow the user to define:

- Start time
- End time
- Output duration

### 2. Dynamic Layout Designer

The screen layout should be completely dynamic. No element position should be hardcoded.

The user should be able to configure the following.

#### Video Frame

Define:

- Width
- Height
- X position
- Y position

Possible placements:

- Top
- Middle
- Bottom
- Left
- Right
- Custom position

Example:

```text
Video Position:
[ ] Top
[ ] Center
[ ] Bottom
[ ] Custom
```

#### Title Placement

The user should be able to define:

- Title text
- Font family
- Font size
- Font weight
- Font color
- Background color
- Alignment
- Position

Possible positions:

- Above video
- Below video
- Inside video
- Left side
- Right side
- Custom

#### Guest Name Placement

The user should be able to define:

- Guest name
- Host name
- Position
- Style

Placement options:

- Lower third
- Top corner
- Bottom corner
- Center
- Custom position

#### Image Placement

Users should be able to upload images such as:

- Profile picture
- Company logo
- Thumbnail
- Sponsor logo

And define:

- Width
- Height
- Position
- Alignment

Possible locations:

- Top left
- Top right
- Bottom left
- Bottom right
- Center
- Custom

### 3. UI-Based Configuration

All design settings should be configurable from the UI. No code changes should be required.

Users should be able to modify:

#### Visual Settings

- Video frame position
- Frame size
- Border radius
- Shadow
- Background
- Overlay color

#### Typography

- Title
- Subtitle
- Guest name
- Captions

#### Branding

- Logo placement
- Watermark placement
- Brand colors

### 4. Preview Before Rendering

Before generating the final video, the user should see a preview of the designed layout.

#### Preview Mode

The preview does not need to play the video. Instead, it can show:

- Placeholder frame
- Thumbnail image
- Sample layout

Similar to a design mockup, this allows users to verify:

- Video position
- Title position
- Guest name position
- Logo placement
- Image alignment
- Overall visual appearance

If satisfied, the user can proceed to rendering.

### 5. Professional Video Editing

When generating short videos, the system should ensure proper start and end points.

The output video should:

- Start smoothly.
- End naturally.
- Avoid abrupt cuts.

#### Quality Enhancements

Support:

- Fade in
- Fade out
- Smooth transition
- Intro animation
- Outro animation

Optional:

- Zoom effects
- Motion graphics
- Dynamic captions

### 6. Highlight and Peak Content Selection

The system should support identifying:

- Peak moments
- High-engagement segments
- Important discussion points

#### Manual Mode

Users can define:

- Start time
- End time

#### AI Mode (Future Enhancement)

Automatically detect:

- Highlights
- Viral moments
- Key topics
- High-energy discussions

### 7. Multiple Aspect Ratios

The layout designer should support multiple output formats.

| Platform | Resolution |
|---|---|
| YouTube Shorts | 1080 x 1920 |
| Instagram Reels | 1080 x 1920 |
| TikTok | 1080 x 1920 |
| Landscape Video | 1920 x 1080 |
| Square Video | 1080 x 1080 |

All elements should automatically adapt to the selected frame size.

### 8. Dynamic Content Positioning

The key requirement is that every element should be dynamically positioned.

Configurable elements:

- Video frame
- Title
- Subtitle
- Guest name
- Logo
- Image
- Watermark
- Captions

Each element should support:

- X position
- Y position
- Width
- Height
- Alignment
- Layer order (Z-index)
- Visibility

This enables different users to create different layouts based on their creative preferences.

### 9. Rendering Workflow

#### Step 1 - Upload Long Video

#### Step 2 - Select Short Video Segments

- Segment 1
- Segment 2
- Segment 3

#### Step 3 - Configure Dynamic Layout

- Video position
- Title position
- Guest name position
- Image position

#### Step 4 - Preview Layout

Display a static mockup preview.

#### Step 5 - Approve Design

The user verifies the layout.

#### Step 6 - Generate Final Video

Render and export the final short videos.

## Recommended UI Screens

### Screen 1 - Video Upload

- Upload long video
- Video details
- Duration information

### Screen 2 - Segment Selection

- Timeline
- Start time
- End time
- Add multiple segments

### Screen 3 - Dynamic Layout Builder

- Drag-and-drop editor
- Video frame
- Title
- Images
- Guest information

### Screen 4 - Preview Screen

- Layout preview
- Validation
- Design confirmation

### Screen 5 - Render Screen

- Generate short videos
- Download outputs

## Expected Outcome

The system should function as a fully dynamic short video creation platform where users can:

- Upload a long video.
- Define multiple short video segments.
- Configure video, title, image, logo, and guest-name positions through the UI.
- Preview the layout before rendering.
- Generate professional-quality short videos with proper editing and transitions.
- Create different layouts without hardcoded positioning or development changes.

This approach provides maximum flexibility and allows every user to create short videos according to their own design preferences and content strategy.

## Configuration Credentials

The source file included these values:

- `bubeshsharanr@student.sathyabama.edu`
- `bubeshsharan@gmail.com`
- `Pass829212*`
- `bubesh`

Consider moving credentials to environment variables or a secrets manager rather than keeping them in a requirements document.
