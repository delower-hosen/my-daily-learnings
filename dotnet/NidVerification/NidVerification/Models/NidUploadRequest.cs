using Microsoft.AspNetCore.Mvc;

namespace NidVerification.Models
{
    public class NidUploadRequest
    {
        [FromForm(Name = "nidImage")]
        public IFormFile NidImage { get; set; } = default!;
    }
}