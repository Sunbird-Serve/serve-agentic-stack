#!/usr/bin/env python3
"""
SERVE AI Platform Backend Testing
Tests all API endpoints and service integrations
"""
import requests
import sys
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

# Use production backend URL from frontend config
BASE_URL = "https://serve-platform-core.preview.emergentagent.com"

class ServeAITester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def log_test_result(self, name: str, success: bool, details: str = "", data: Any = None):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
        
        result = {
            "test": name,
            "success": success,
            "details": details,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        self.test_results.append(result)
        
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {name}: {details}")

    def run_test(self, name: str, method: str, endpoint: str, expected_status: int, 
                data: Optional[Dict] = None, headers: Optional[Dict] = None) -> tuple[bool, Dict]:
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        default_headers = {'Content-Type': 'application/json'}
        if headers:
            default_headers.update(headers)

        try:
            if method == 'GET':
                response = requests.get(url, headers=default_headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=default_headers, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=default_headers, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=default_headers, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            success = response.status_code == expected_status
            response_data = {}
            
            try:
                response_data = response.json()
            except:
                response_data = {"text": response.text, "status_code": response.status_code}
            
            details = f"Status {response.status_code}" + (f" (expected {expected_status})" if not success else "")
            self.log_test_result(name, success, details, response_data)
            
            return success, response_data

        except Exception as e:
            self.log_test_result(name, False, f"Exception: {str(e)}")
            return False, {}

    def test_health_endpoints(self):
        """Test all health check endpoints"""
        print("\n🏥 Testing Health Endpoints")
        
        # Platform health
        self.run_test("Platform Health Check", "GET", "/api/health", 200)
        
        # Root endpoint
        self.run_test("Root Endpoint", "GET", "/api/", 200)
        
        # Orchestrator health
        self.run_test("Orchestrator Health", "GET", "/api/orchestrator/health", 200)
        
        # Onboarding agent health
        self.run_test("Onboarding Agent Health", "GET", "/api/agents/onboarding/health", 200)

    def test_mcp_capabilities(self):
        """Test MCP capability endpoints"""
        print("\n🔧 Testing MCP Capabilities")
        
        # Test session management capabilities
        test_session_id = str(uuid.uuid4())
        
        # Test start session
        start_data = {
            "channel": "web_ui",
            "persona": "new_volunteer"
        }
        success, response = self.run_test(
            "MCP Start Session", 
            "POST", 
            "/api/mcp/capabilities/onboarding/start-session", 
            200, 
            start_data
        )
        
        if success and response.get("status") == "success":
            test_session_id = response.get("data", {}).get("session_id", test_session_id)
            self.session_id = test_session_id
        
        # Test missing fields check
        self.run_test(
            "MCP Get Missing Fields",
            "POST",
            "/api/mcp/capabilities/onboarding/get-missing-fields",
            200,
            {"session_id": test_session_id}
        )
        
        # Test save confirmed fields
        self.run_test(
            "MCP Save Confirmed Fields",
            "POST",
            "/api/mcp/capabilities/onboarding/save-confirmed-fields",
            200,
            {
                "session_id": test_session_id,
                "fields": {"full_name": "Test User", "email": "test@example.com"}
            }
        )

        # Test resume context
        self.run_test(
            "MCP Resume Context",
            "POST",
            "/api/mcp/capabilities/onboarding/resume-context",
            200,
            {"session_id": test_session_id}
        )

        # Test sessions listing
        self.run_test(
            "MCP List Sessions",
            "GET",
            "/api/mcp/capabilities/onboarding/sessions?limit=10",
            200
        )

    def test_orchestrator_interaction(self):
        """Test orchestrator interaction endpoint"""
        print("\n🎯 Testing Orchestrator Interactions")
        
        # Test initial interaction
        interaction_data = {
            "message": "Hello, I want to volunteer",
            "channel": "web_ui",
            "persona": "new_volunteer",
            "channel_metadata": {}
        }
        
        success, response = self.run_test(
            "Orchestrator Interact - Initial",
            "POST",
            "/api/orchestrator/interact",
            200,
            interaction_data
        )
        
        # Extract session ID for follow-up
        if success and "session_id" in response:
            session_id = response["session_id"]
            self.session_id = session_id
            
            # Test follow-up interaction
            followup_data = {
                "session_id": session_id,
                "message": "My name is John Doe and I'm interested in volunteering",
                "channel": "web_ui"
            }
            
            self.run_test(
                "Orchestrator Interact - Follow-up",
                "POST", 
                "/api/orchestrator/interact",
                200,
                followup_data
            )
            
            # Test session retrieval
            self.run_test(
                "Get Session State",
                "GET",
                f"/api/orchestrator/session/{session_id}",
                200
            )

    def test_onboarding_agent_turn(self):
        """Test onboarding agent turn endpoint"""
        print("\n🤖 Testing Onboarding Agent")
        
        if not self.session_id:
            self.session_id = str(uuid.uuid4())
        
        # Test agent turn
        turn_data = {
            "session_id": self.session_id,
            "session_state": {
                "id": self.session_id,
                "channel": "web_ui",
                "persona": "new_volunteer",
                "workflow": "new_volunteer_onboarding",
                "active_agent": "onboarding",
                "status": "active",
                "stage": "init",
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            },
            "user_message": "Hi there, I want to help!",
            "conversation_history": []
        }
        
        self.run_test(
            "Onboarding Agent Turn",
            "POST",
            "/api/agents/onboarding/turn",
            200,
            turn_data
        )

    def test_error_handling(self):
        """Test error handling and edge cases"""
        print("\n⚠️  Testing Error Handling")
        
        # Test invalid session ID
        self.run_test(
            "Invalid Session ID",
            "GET",
            "/api/orchestrator/session/invalid-uuid",
            422  # Should return validation error
        )
        
        # Test malformed request
        self.run_test(
            "Malformed Interaction Request",
            "POST",
            "/api/orchestrator/interact",
            422,  # Should return validation error
            {"invalid": "data"}
        )
        
        # Test non-existent endpoint
        self.run_test(
            "Non-existent Endpoint",
            "GET",
            "/api/nonexistent/endpoint",
            404
        )

    def print_summary(self):
        """Print test summary"""
        print(f"\n📊 Test Summary")
        print(f"Tests Run: {self.tests_run}")
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Tests Failed: {self.tests_run - self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed / self.tests_run * 100):.1f}%" if self.tests_run > 0 else "N/A")
        
        # List failures
        failures = [r for r in self.test_results if not r["success"]]
        if failures:
            print(f"\n❌ Failed Tests:")
            for failure in failures:
                print(f"  - {failure['test']}: {failure['details']}")
        
        return self.tests_passed, self.tests_run, failures

def main():
    """Main test runner"""
    print("🚀 Starting SERVE AI Platform Backend Tests")
    print(f"Backend URL: {BASE_URL}")
    
    tester = ServeAITester()
    
    try:
        # Run all test suites
        tester.test_health_endpoints()
        tester.test_mcp_capabilities()
        tester.test_orchestrator_interaction()
        tester.test_onboarding_agent_turn()
        tester.test_error_handling()
        
        # Print results
        passed, total, failures = tester.print_summary()
        
        # Save detailed results
        with open("/app/backend_test_results.json", "w") as f:
            json.dump({
                "summary": {
                    "passed": passed,
                    "total": total,
                    "success_rate": (passed / total * 100) if total > 0 else 0
                },
                "results": tester.test_results,
                "timestamp": datetime.utcnow().isoformat()
            }, f, indent=2)
        
        return 0 if passed == total else 1
        
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"\n💥 Critical error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())