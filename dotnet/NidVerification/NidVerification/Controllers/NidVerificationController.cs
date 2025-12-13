using Microsoft.AspNetCore.Mvc;
using NidVerification.Extension;
using NidVerification.Models;
using OpenCvSharp;
using System.Text.RegularExpressions;
using Tesseract;

namespace NidVerification.Controllers;

[ApiController]
[Route("api/[controller]")]
public class NidVerificationController : ControllerBase
{
    // IMPORTANT: tessdata must contain eng.traineddata & ben.traineddata
    private static readonly string TessDataPath = Path.Combine(AppContext.BaseDirectory, "tessdata");

    [HttpPost("verify")]
    [Consumes("multipart/form-data")]
    public async Task<IActionResult> Verify([FromForm] NidUploadRequest request)
    {
        if (request.NidImage == null || request.NidImage.Length == 0)
            return BadRequest(new { success = false, message = "No file uploaded." });

        byte[] rawImage;
        using (var ms = new MemoryStream())
        {
            await request.NidImage.CopyToAsync(ms);
            rawImage = ms.ToArray();
        }

        // 1. Preprocess image
        byte[] processedBytes;
        using (var ms = new MemoryStream(rawImage))
        {
            using var processedStream = PreprocessForOcr(ms);
            processedBytes = StreamToBytes(processedStream);
        }

        // 2. OCR
        string text;
        try
        {
            text = RunTesseract(rawImage);
        }
        catch (Exception ex)
        {
            return StatusCode(500, new { success = false, message = ex.Message });
        }

        // 3. Extract likely NID number
        string? nid = ExtractNidFromOcrText(text);

        return Ok(new
        {
            success = nid != null,
            nidNumber = nid,
            extractedText = text,
        });
    }

    // ---------------- OCR + Image Processing ----------------

    private static byte[] StreamToBytes(Stream input)
    {
        if (input == null)
            throw new ArgumentNullException(nameof(input));

        if (input.CanSeek)
            input.Position = 0;

        using var ms = new MemoryStream();
        input.CopyTo(ms);
        return ms.ToArray();
    }

    private static Stream PreprocessForOcr(Stream fileStream)
    {
        MemoryStream memoryStream = new MemoryStream();
        fileStream.CopyTo(memoryStream);
        // Load the image
        Mat img = Cv2.ImDecode(memoryStream.ToArray(), ImreadModes.Color);


        // Convert the image to grayscale
        Mat gray = new Mat();
        Cv2.CvtColor(img, gray, ColorConversionCodes.BGR2GRAY);

        // Apply a threshold to binarize the image
        Mat thresh = new Mat();
        Cv2.Threshold(gray, thresh, 0, 255, ThresholdTypes.BinaryInv | ThresholdTypes.Otsu);

        // Use the Hough Line Transform to detect the lines in the image
        LineSegmentPoint[] lines = Cv2.HoughLinesP(thresh, 1, Math.PI / 180, 100, 100, 10);

        // Compute the angle of each line with respect to the x-axis
        List<double> angles = new List<double>();
        foreach (LineSegmentPoint line in lines)
        {
            double angle = Math.Atan2(line.P2.Y - line.P1.Y, line.P2.X - line.P1.X) * 180 / Math.PI;
            angles.Add(angle);
        }

        // Calculate the median of the angles to get an estimate of the angle to rotate the image
        double median_angle = angles.Median();
        Console.WriteLine("Estimated angle to rotate image: " + median_angle);

        // Rotate the image using the estimated angle
        Point2f center = new Point2f(img.Cols / 2f, img.Rows / 2f);
        Mat rot_mat = Cv2.GetRotationMatrix2D(center, median_angle, 1);
        Mat rotated_img = new Mat();
        Cv2.WarpAffine(img, rotated_img, rot_mat, img.Size());

        // Convert Mat to MemoryStream
        MemoryStream ms = new MemoryStream();
        rotated_img.ToMemoryStream(".jpg").CopyTo(ms);
        return ms;
    }

    private static string RunTesseract(byte[] imageBytes)
    {
        if (!Directory.Exists(TessDataPath))
            throw new Exception($"tessdata folder not found at: {TessDataPath}");

        using var engine = new TesseractEngine(TessDataPath, "eng+ben", EngineMode.Default);
        using var pix = Pix.LoadFromMemory(imageBytes);
        using var page = engine.Process(pix);

        return page.GetText() ?? "";
    }

    private static string? ExtractNidFromOcrText(string ocrText)
    {
        if (string.IsNullOrWhiteSpace(ocrText)) return null;

        // 1) Normalize common unicode noise and Bengali digits → latin digits
        string normalized = NormalizeDigitsAndWhitespace(ocrText);

        // 2) Look for contextual patterns (English + Bangla)
        // common English/Bangla phrases near NID label
        var contextPatterns = new[]
        {
        @"\bNID(?:\s*No(?:\.|:)?|\b)?\s*[:\-]?\s*([\d\s]{6,25})",         // NID No 870 307 4545
        @"\bNID\b.*?([\d\s]{6,25})",
        @"\bNID\s*No\b.*?([\d\s]{6,25})",
        @"\bNID\s*No[:\-]?\s*([\d\s]{6,25})",
        @"\bNational\s*ID(?:\s*No)?[:\-]?\s*([\d\s]{6,25})",
        @"\bNID\s*No\.\s*([\d\s]{6,25})",
        // Bangla / Bengali patterns (common variants)
        @"\bNID ?নং[:\s\-]*([\d০-৯\s]{6,25})",
        @"\bজাতীয় পরিচয়পত্র[:\s\-]*([\d০-৯\s]{6,25})",
        @"\bNID[:\s\-]*([\d০-৯\s]{6,25})",
        @"\bNIDNo[:\s\-]*([\d০-৯\s]{6,25})"
    };

        foreach (var pat in contextPatterns)
        {
            var m = Regex.Match(ocrText, pat, RegexOptions.IgnoreCase | RegexOptions.Singleline);
            if (m.Success && m.Groups.Count > 1)
            {
                var candidate = m.Groups[1].Value;
                candidate = NormalizeDigitsAndWhitespace(candidate);
                candidate = Regex.Replace(candidate, @"\s+", "");
                candidate = ConvertBanglaDigitsToEnglish(candidate);
                if (IsPlausibleNid(candidate)) return candidate;
            }
        }

        // 3) No contextual hit — fallback: find all digit sequences and pick best
        // Convert Bengali digits in whole normalized text first
        string digitsNormalized = ConvertBanglaDigitsToEnglish(normalized);

        // Replace any non-digit with space so sequences split cleanly
        var digitOnly = Regex.Replace(digitsNormalized, @"[^\d]", " ");

        // Get all contiguous sequences of digits
        var seqs = Regex.Matches(digitOnly, @"\d{6,20}") // lower bound 6 to include shorter OCR fragments
                       .Cast<Match>()
                       .Select(m => m.Value)
                       .Where(s => !string.IsNullOrWhiteSpace(s))
                       .ToArray();

        if (seqs.Length == 0) return null;

        // Prefer sequences with length between 10 and 17 (typical NID lengths)
        var good = seqs.Where(s => s.Length >= 10 && s.Length <= 17).ToArray();
        if (good.Length > 0)
        {
            // pick the one nearest to "NID" word if possible
            var nidIndex = IndexOfIgnoreCase(ocrText, "NID");
            if (nidIndex >= 0)
            {
                // find the candidate whose index is closest to nidIndex
                int bestIdx = -1;
                int bestDist = int.MaxValue;
                foreach (var cand in good)
                {
                    var idx = ocrText.IndexOf(cand, StringComparison.OrdinalIgnoreCase);
                    if (idx >= 0)
                    {
                        var dist = Math.Abs(idx - nidIndex);
                        if (dist < bestDist)
                        {
                            bestDist = dist;
                            bestIdx = idx;
                        }
                    }
                }
                if (bestIdx >= 0)
                {
                    // find the candidate at bestIdx
                    var chosen = good.OrderBy(s => Math.Abs(ocrText.IndexOf(s, StringComparison.OrdinalIgnoreCase) - nidIndex)).First();
                    return chosen;
                }
            }

            // otherwise, pick longest from good
            return good.OrderByDescending(s => s.Length).First();
        }

        // 4) Fallback pick the longest digit sequence found
        var longest = seqs.OrderByDescending(s => s.Length).First();
        return longest;
    }

    private static string NormalizeDigitsAndWhitespace(string input)
    {
        if (string.IsNullOrEmpty(input)) return input;
        // Normalize different whitespace and common OCR oddities
        var s = input.Replace('\u00A0', ' ')   // non-breaking space
                     .Replace('\u200B', ' ')   // zero width space
                     .Replace('\u200C', ' ')   // zero width non-joiner
                     .Replace('\u200D', ' ')
                     .Replace('\r', ' ')
                     .Replace('\n', ' ')
                     .Trim();
        return s;
    }

    private static string ConvertBanglaDigitsToEnglish(string s)
    {
        if (string.IsNullOrEmpty(s)) return s;
        return s
            .Replace('০', '0').Replace('১', '1').Replace('২', '2')
            .Replace('৩', '3').Replace('৪', '4').Replace('৫', '5')
            .Replace('৬', '6').Replace('৭', '7').Replace('৮', '8')
            .Replace('৯', '9');
    }

    private static bool IsPlausibleNid(string digits)
    {
        if (string.IsNullOrEmpty(digits)) return false;
        if (!Regex.IsMatch(digits, @"^\d{8,17}$")) return false; // allow 8-17 digits
                                                                 // you can add more domain-specific checks here (prefixes, checksum, etc.)
        return true;
    }

    private static int IndexOfIgnoreCase(string source, string value)
    {
        if (string.IsNullOrEmpty(source) || string.IsNullOrEmpty(value)) return -1;
        return source.IndexOf(value, StringComparison.OrdinalIgnoreCase);
    }

}
